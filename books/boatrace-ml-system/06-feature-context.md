---
title: "特徴量パイプラインの高速化: FeatureContext"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 月次の重み学習は「6 か月 × 全レースの特徴量を再計算する」バッチです。単日向けに書いた特徴量関数を 181 回呼ぶと何が起きるか、学習パイプラインのコストをどの単位で計測するか |
| システム | 「素朴に正しい実装」を計測して直す手順。セッションインデックスの事前計算、メモ化、公開 API を変えないキャッシュの入れ方、旧実装との出力一致(parity)テスト、冪等性を使った本番での回帰検出、2 段階ロールアウト |

第 4 章と第 5 章で作った特徴量は、`compute_features_for_day(repo, day)` という「1 日分の特徴量を返す関数」に
集約されています。毎朝の daily-sync(第 11 章)はこれを 1 回呼ぶだけです。ところが第 7 章の重み学習は、
同じ関数を過去 6 か月ぶん、181 回呼びます。この章は、その 181 回が約 75 分かかって Cloud Run Job の
タイムアウトに当たった件と、それを計測して直した記録です。モデルの話はほとんど出てきません。
主題は「ML の前に計測」です。

## 1. 観測: 月次重み学習が 75 分かかる

### 1.1 タイムアウトのログ

重み学習を行う `scripts/build_weights.py` は、Cloud Run Jobs の `monthly-weights` として毎月 1 日 06:00 JST に
起動され、`--task-timeout=3600s` で動いています。2026-05-23 の実行ログは、30 日ごとの進捗が次のようになっていました。

| 進捗 | 経過時間 | 1 日あたり |
| --- | --- | --- |
| 0〜30 日 | 5:16 | 10.5 秒 |
| 30〜60 日 | +8:53 | 17.8 秒 |
| 60〜90 日 | +11:43 | 23.4 秒 |
| 90〜120 日 | +12:33 | 25.1 秒 |
| 120〜150 日 | +13:03 | 26.1 秒 |
| 150〜181 日 | 強制終了 | – |

単純に外挿すると訓練テーブルの構築(`build_training_table`)だけで約 75 分で、3,600 秒には収まりません。
もう一つ、1 日あたりの処理時間が 10.5 秒から 26.1 秒へ単調に伸びている点にも注意が要ります。
1 日ぶんのコストが一定ならこの列は平らになるはずで、伸びている以上、日を追うごとに何かが積み上がっています。
原因が I/O なのか pandas のメモリ圧迫や GC なのかは、この時点では分かりません。設計書はこれをリスクとして残し、
デプロイ後に確認する項目にしました(3.3 節)。

### 1.2 どこで時間を使っているか

`compute_features_for_day(repo, day)` が 1 日ぶんの特徴量を作るために読むファイルを、
設計時点の実装で数えたのが次の表です(181 日換算は 6 か月ぶんの呼び出しの合計)。

| 処理 | 1 日あたりの I/O | 181 日換算 |
| --- | --- | --- |
| 静的テーブル(枠別勝率、モーター得点表、水面パラメータ)の読み込み | 3 CSV(不変) | 543 回 |
| `load_motor_period_starts`(モーター期起算日) | 最大 15 日ぶんの `motor_stats/*.csv` 探索 | 約 2,700 回 |
| `detect_session_end_days`(24 場) | 24 場 × 90 日の `race_cards/*.csv` 存在チェックと読み込み | **390,960 回** |
| `extract_runs_for_session` | 24 場 × 最大 5 節の `race_cards` と `title` 再読込 | 約 21,720 回 |
| 当日固有のデータ(`recent_*`、`previews/*`、当日の `race_cards`) | 7 CSV | 1,267 回 |

支配的なのは `detect_session_end_days` の 39 万回です。第 5 章のモーター指数は「同じ場での直近 6 節の成績」を使うため、
各場について節(連続開催日のかたまり)がいつ終わったかを知る必要があります。既存実装は対象日から 90 日遡って
1 日ずつ `race_cards` を開き、その場のレースコードが含まれるかを調べていました。連続する 2 日でこの走査が参照する
ファイルはほぼ完全に重なります。5 月 10 日の計算で開いた 90 個のうち 89 個は 5 月 11 日でも開かれ、
設計書はこれを「ファイル I/O の約 99% が冗長」と見積もりました。

### 1.3 根本原因は「関数が毎回ゼロから履歴を組む」構造

個々の関数にバグがあったわけではありません。`load_motor_history(repo, target_day)` はリポジトリのパスと日付だけを受け取り、
必要な履歴を毎回ゼロから組み立てます。呼び出しの間に状態を持つ場所がないので、これ以外の書き方ができません。
1 日だけ呼ぶ daily-sync ではそれで十分で、10〜25 秒は問題になりませんでした。`build_weights.py` は
この単日向けの関数をループで 181 回呼んだだけです。

つまり原因は、関数が想定していた呼び出しパターン(単日)と実際の呼び出しパターン(6 か月の連続日)の食い違いにあります。
特徴量関数を書いた時点では見えず、月次バッチにつないで初めて表面化します。実行時間は「1 回あたり」ではなく
「呼び出しパターンごと」に計測する必要がある、というのがこの節の教訓です。

## 2. 設計: FeatureContext

### 2.1 公開 API を変えない

対処として、`boatrace.index_features` に `FeatureContext` というクラスを新設しました。日付の窓(window)を
覆うキャッシュを 1 つ作り、その窓の中の日付について特徴量を計算するときに共有します。設計上の制約は 3 つです。

1. `compute_features_for_day(repo, day)` の呼び方は変えない。キーワード引数 `ctx` を足すだけにする
2. `load_motor_history` や `detect_session_end_days` などのモジュール関数はシグネチャを変えずに残す。
   `scripts/tests/unit/test_motor_ability.py` がこれらを直接 import しているため
3. 出力 CSV の値は byte-identical に保つ

3 が最も重要です。この関数の出力は `data/estimate/` 配下の CSV としてコミットされ、予想ページに使われます。
出力が 1 バイトも変わらないと決めておけば、正しさの検証を「旧実装と比べて差分がゼロか」という機械的な確認に
落とせます。高速化と挙動変更を同じ変更に混ぜないのは、この検証手段を保つためです。

```python:index_features.py(抜粋)
def compute_features_for_day(
    repo: Path, day: dt.date, *, ctx: "FeatureContext | None" = None,
) -> pd.DataFrame:
    if ctx is None:
        ctx = FeatureContext(repo, window_start=day, window_end=day)
    elif not (ctx.window_start <= day <= ctx.window_end):
        raise ValueError(
            f"day={day} is outside ctx window "
            f"[{ctx.window_start}, {ctx.window_end}]. "
            f"Construct a Context covering the day, or omit ctx for single-day use."
        )
```

`ctx` を省略すると、その日だけを窓とする Context を内部で作って使うので、単日呼び出しの `build_index.py` は無変更で
新しい経路を通ります。窓の外の日付で `ValueError` にするのは、後述するセッションインデックスが「窓の開始日 − 90 日」
からしか作られないためです。黙って受け付けると履歴が途中で切れたまま、エラーも出さずに間違ったモーター指数を返します。
第 12 章で扱う「沈黙する失敗」を設計の段階で塞いでいます。

### 2.2 セッションインデックスの事前計算

中核の最適化は、`detect_session_end_days` が行っていた「対象日ごとに 24 場 × 90 日の存在チェック」を、
窓全体で 1 回の走査に置き換えることです。

```python:index_features.py(抜粋)
def _build_session_index(self) -> dict[str, list[dt.date]]:
    earliest = self.window_start - dt.timedelta(days=MOTOR_HISTORY_LOOKBACK_DAYS)
    latest = self.window_end - dt.timedelta(days=1)
    out: dict[str, list[dt.date]] = {s: [] for s in self._all_stadiums}
    d = earliest
    while d <= latest:
        rc = self.race_cards_for(d)
        if rc is not None and not rc.empty and "レースコード" in rc.columns:
            codes = rc["レースコード"].dropna().astype(str)
            present = set(codes.str[8:10].unique())
            for s in present:
                if s in out:
                    out[s].append(d)
        d += dt.timedelta(days=1)
    return out
```

レースコードの 9〜10 文字目が場コードです(第 2 章)。「窓の開始日 − 90 日」から「窓の終了日 − 1 日」まで
1 日ずつ `race_cards` を開き、その日に開催があった場の一覧を `{場コード: [開催日, ...]}` に積んでいきます。
終了日当日を含めないのは、既存実装が「対象日当日の節は履歴に含めない」設計だったことを踏襲するためです。

対象日ごとの節の一覧は、このインデックスからメモリ上で導きます。

```python:index_features.py(抜粋)
def sessions_for(self, target_day, stadium):
    if self._session_index is None:
        self._session_index = self._build_session_index()
    cutoff_min = target_day - dt.timedelta(days=MOTOR_HISTORY_LOOKBACK_DAYS)
    in_window = [d for d in self._session_index.get(stadium, [])
                 if cutoff_min <= d < target_day]
    if not in_window:
        return []
    sessions: list[list[dt.date]] = []       # 連続日を 1 節として束ねる
    cur = [in_window[0]]
    for d in in_window[1:]:
        if (d - cur[-1]).days <= 1:
            cur.append(d)
        else:
            sessions.append(cur)
            cur = [d]
    sessions.append(cur)
    return sessions[-MOTOR_HISTORY_LOOKBACK_MAX_SESSIONS:][::-1]   # 新→旧
```

束ね方(日差 1 日以内なら同じ節、直近 10 節まで、新しい順)は既存の `detect_sessions` と同じ条件式です。
入力も規則も同じなので結果は一致し、この一致は後でテストで確認します。`race_cards` の存在チェックは
対象日ごとの 24 × 90 回から窓全体で約 270 回(181 日 + 90 日の遡り)へ、設計書の見積もりで約 390,000 回 → 約 270 回に減ります。

### 2.3 メモリキャッシュとメモ化

残りの冗長な I/O は 3 種類のキャッシュで消しました。方式が違うのは、それぞれ量を見積もった結果が違うからです。

**`race_cards` と `title` のメモリキャッシュ(上限なし)**。日付をキーに `DataFrame` をそのまま保持します。
monthly-weights Job は 8 か月ぶんの sparse checkout で動くため、ファイル数は約 240、1 ファイル約 30 KB で合計約 7 MB、
`title` も同程度です。Cloud Run の 2 GiB に対して無視できるので、LRU などの上限管理は入れていません。

**`load_motor_period_starts` の日次メモ化**。14 日遡って `motor_stats` を探しますが、ファイルが小さく呼び出しも 181 回なので、
対象日をキーにしたメモ化で十分です。

**`extract_runs_for_session` の `(場, 節最終日)` 単位のメモ化**。1 節ぶんの `MotorRun` を組み立てるこの関数は、
`title` CSV が無いときの `"G2_G3_一般"` フォールバック、モーター番号の「先勝ち」辞書、`D1走1〜D7走2` の 14 スロット展開など
50 行ほどの非自明な処理を含みます。書き直しは回帰の温床になるため、既存関数をそのまま呼んで結果をメモ化するだけにしました
(純関数化する案は 2.5 節で却下)。`race_cards` の二重読みは残りますが、呼び出し回数は「窓の日数 × 24 場 × 節数」で
約 1,350 回に抑えられます。

`motor_history(day)` は、この節の一覧と `MotorRun` を組み合わせて `load_motor_history(repo, day)` と同じ辞書を返します。
ロジックは既存関数のコピーで、ファイルアクセスだけをキャッシュ経由に差し替えています。

![素朴版と FeatureContext のファイルアクセス](/images/boatrace-ml-system/feature-context-io.png)
<!-- 図: 左に素朴版: 「day1, day2, ..., day181」それぞれの箱から race_cards の 90 日ぶんのファイル群へ矢印が伸び、矢印が重なり合っている。右に FeatureContext: race_cards 群を 1 回だけ走査して session_index(場→開催日リスト)と race_cards_cache を作り、day1..day181 はそのインデックスとキャッシュだけを参照している。矢印の本数の差で 41 万回 → 270 回を表現する -->

### 2.4 見積もり

設計書に記録した見積もりです。ファイル I/O の回数と、実時間の両方を保守側で置いています。

| 項目 | 旧 | 新 |
| --- | --- | --- |
| 静的テーブルの読み込み | 181 × 3 = 543 回 | 3 回 |
| `race_cards` の open | 約 410,000 回 | 約 270 回 |
| `extract_runs_for_session` の呼び出し | 約 22,000 回 | 約 1,350 回 |
| `motor_stats` の open | 約 2,700 回 | 約 270 回 |

実時間は、`_has_races_at` の存在チェックが 20〜35 分 → 約 3 秒、`extract_runs_for_session` が 18〜37 分 → 約 2 分に減り、
当日固有の I/O(約 30 秒)と pandas のメインループ(`groupby` / `hensachi` / `iterrows`、1〜3 分)は不変で、
`build_training_table` の合計は約 75 分 → 約 10〜15 分の見積もりです。設計書は「5 分は楽観的な下限、15 分は保守的な上限」と
注記しています。1.1 節の劣化がすべて I/O 起因なら 10 分を切る可能性があり、pandas や GC 由来の要因が混じっていれば
キャッシュでは取りきれない、という条件付きの見積もりで、実測でどちらだったかを判定する方法は次節で決めています。

### 2.5 検討して却下した代替案

| 案 | 概要 | 却下理由 |
| --- | --- | --- |
| `@functools.lru_cache` をモジュール関数に付ける | `load_waku_table` 等をプロセス全体でキャッシュ | テスト間でキャッシュが漏れる。`tmp_path` で別リポジトリを使う `test_motor_ability.py` が壊れる |
| `extract_runs_for_session` の純関数化 | `DataFrame` を引数に取り、ファイル読みと分離 | 設計としては綺麗だが PR の範囲が膨らみ、回帰の面が広がる。今回はメモ化で済ませる |
| セッションインデックスの並列構築 | 270 ファイルの読みを async / thread で並列化 | 直列でも約 3 秒。複雑さに見合わない |
| 事前計算結果を parquet で永続化 | 特徴量をリポジトリにコミットして再利用 | Cloud Run Job は stateless で次回は読めない。git にコミットすれば可能だが diff が肥大する |
| `multiprocessing.Pool` で日付並列 | 181 日を worker で分割 | worker ごとに Context を持つとキャッシュ効果が落ちる。本リファクタだけで十分速くなる |

最初の案は「デコレータを付ければ終わり」に見えます。却下理由がテストの独立性であることは、キャッシュのスコープを
プロセスではなく Context オブジェクトに閉じ込めた理由そのものです。Context はテストごとに作り直せるので、キャッシュが漏れません。

## 3. 検証とロールアウト

### 3.1 旧実装との出力一致(parity)テスト

`scripts/tests/unit/test_feature_context.py` は、期待値を手で書くのではなく「旧実装と同じ結果を返すか」を確認します。
旧実装が仕様であり、目標は「何も変えないこと」だからです。`tmp_path` に最小構成のリポジトリを作り、次の観点を検証しています。

- 窓の検証: 終了日が開始日より前なら `ValueError`、窓の外の日付を `ctx` 付きで渡しても `ValueError`、窓の両端の日付は有効
- `session_end_days_for` と `detect_session_end_days`、`motor_history` と `load_motor_history` の一致。連続日、ギャップ、
  対象日当日の除外、上限 10 節での切り詰め、窓の中の全日付を含む(`MotorRun` は frozen dataclass なので `==` で比較できる)
- `compute_features_for_day` の `ctx` あり・なしの一致を `pd.testing.assert_frame_equal` で確認。単日と、窓の中の全日付
- 窓の中に `race_cards` が無い日があっても失敗しないこと、静的テーブルが 2 回目以降同じオブジェクトを返すこと(`is`)

```python:test_feature_context.py(抜粋)
def test_compute_with_ctx_matches_without_ctx_across_window(tmp_path: Path):
    repo, start, end = _multi_day_repo(tmp_path)
    ctx = FeatureContext(repo, window_start=start, window_end=end)

    d = start
    while d <= end:
        no_ctx = compute_features_for_day(repo, d)
        with_ctx = compute_features_for_day(repo, d, ctx=ctx)
        pd.testing.assert_frame_equal(
            no_ctx, with_ctx,
            obj=f"compute_features_for_day mismatch on {d}",
        )
        d += dt.timedelta(days=1)
```

窓の中の全日付を回している点が要点です。Context のキャッシュは呼び出し順に依存して育つので、
1 日だけの比較では「2 日目以降、前日のキャッシュを引きずって間違える」種類の不具合を見つけられません。

### 3.2 本番での回帰検出: 冪等性を使う

ユニットテストは合成データなので、本物の CSV との一致は別に確認します。デプロイ前は、過去月(2026-04)の重み CSV を
ローカルで再生成し、`git diff` が空であることを見ました(設計書の記載では `data/estimate/stadium/index_weights/2026-04.csv`。
現在は予想者ごとに `data/estimate/stadium/weights/{predictor_id}/YYYY-MM.csv` へ再編されています)。

本番にも同じ仕組みが組み込まれています。`infra/run-monthly-weights.sh` は `build_weights.py` の出力を `git add` した後に
`git diff --cached --quiet` で差分の有無を調べ、差分がなければコミットしません。つまり過去月を指定して Job を再実行し、
コミットが出なければ出力は byte-identical だったと分かります。冪等に作ってあるバッチは、それ自体が回帰テストになります。
この考え方は第 12 章でも繰り返し使います。

### 3.3 2 段階の PR

変更は 2 つの PR に分けました。

**PR1: Context の導入(配線なし)**。`FeatureContext` クラスと `ctx` キーワード、parity テストを追加し、`build_weights.py` は
触りません。ただし `ctx=None` のときに内部で単日の Context を作る設計なので、毎朝の daily-sync も新しいコード経路を必ず通ります。
マージ後は daily-sync を 1〜2 回、エラー・出力差分・処理時間の異常がないかログで確認しました。

**PR2: `build_weights.py` の配線**。`build_training_table` の先頭で窓全体の Context を作り、ループの中で渡すだけです。

```python:build_weights.py(抜粋)
def build_training_table(repo: Path, start: dt.date, end: dt.date) -> pd.DataFrame:
    ctx = FeatureContext(repo, window_start=start, window_end=end)
    parts = []
    n_days = (end - start).days + 1
    for i, day in enumerate(iter_dates(start, end)):
        feat = compute_features_for_day(repo, day, ctx=ctx)
        ...
    print(
        f"  FeatureContext stats: "
        f"race_cards={len(ctx._race_cards_cache)} "
        f"title={len(ctx._title_cache)} "
        f"runs={len(ctx._runs_cache)} "
        f"period_starts={len(ctx._period_starts_cache)}",
        file=sys.stderr,
    )
```

末尾でキャッシュの件数をログに出しているのは、デプロイ後に「キャッシュが想定どおり効いているか」を
数字で確認するためです。6 か月の窓での期待値は `race_cards ≒ 270`、`title ≒ 270`、`runs ≒ 1,350`、
`period_starts ≒ 181` で、ここから大きく外れていればキャッシュの無効化や窓の不一致を疑います。

PR2 のマージ後は、`gcloud run jobs execute monthly-weights --update-env-vars=TARGET_MONTH=2026-04` で過去月を実行して
コミットが出ない(= 出力に差分がない)ことを確認し、ログの 30 日ごとのスループット(秒/日)が平らになっているかを見ます。
旧実装の 10.5 秒 → 26 秒の劣化が消えていれば劣化は I/O 起因だったと裏付けられ、残っていれば pandas / GC 由来の要因が
あるので追加調査に回します。`--task-timeout` は 3600 秒のまま据え置き、実測に余裕があれば後で短縮する方針です。

結果として、`docs/infrastructure.md` には monthly-weights の所要時間が「実測 10〜15 分(FeatureContext 導入後)」と
記録されています。見積もりの保守側の範囲に収まりました。

## 4. 簡略版コード

設計の本質だけを stdlib のみで書いたものです。素朴版(`detect_sessions` / `load_motor_history`)と `FeatureContext` を
同じファイルに置き、`race_cards` を開いた回数を数えられるようにしています。関数名と定数名は実装に合わせてあります。

```python:feature_context_min.py
STADIUMS = [f"{i:02d}" for i in range(1, 25)]      # 24 場
MOTOR_HISTORY_SESSIONS = 6                          # 採用する節数
MOTOR_HISTORY_LOOKBACK_MAX_SESSIONS = 10            # 剪定前に取得する節数の上限
MOTOR_HISTORY_LOOKBACK_DAYS = 90                    # 節検出のために遡る日数

OPEN_COUNT = 0   # 計測用: race_cards を開いた回数


def read_race_cards(repo: Path, day: dt.date) -> list[dict] | None:
    """その日の race_cards を行の list で返す。無ければ None。open 回数を数える。"""
    global OPEN_COUNT
    p = repo / "race_cards" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}.csv"
    if not p.exists():
        return None
    OPEN_COUNT += 1
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_sessions(open_days: list[dt.date]) -> list[list[dt.date]]:
    """昇順の開催日を、連続日(日差 1 以内)ごとに 1 節へ束ね、新→旧で返す。"""
    sessions: list[list[dt.date]] = []
    for d in open_days:
        if sessions and (d - sessions[-1][-1]).days <= 1:
            sessions[-1].append(d)
        else:
            sessions.append([d])
    return sessions[-MOTOR_HISTORY_LOOKBACK_MAX_SESSIONS:][::-1]


# ─── 素朴版: 対象日ごとに 90 日ぶんのファイルを開き直す ─────────
def _has_races_at(repo: Path, day: dt.date, stadium: str) -> bool:
    rows = read_race_cards(repo, day)
    return bool(rows) and any(r["レースコード"][8:10] == stadium for r in rows)


def detect_sessions(repo: Path, stadium: str, target_day: dt.date) -> list[list[dt.date]]:
    open_days = [target_day - dt.timedelta(days=back)
                 for back in range(MOTOR_HISTORY_LOOKBACK_DAYS, 0, -1)
                 if _has_races_at(repo, target_day - dt.timedelta(days=back), stadium)]
    return group_sessions(open_days)


# ─── FeatureContext: 窓全体で 1 回だけ走査する ──────────────────
class FeatureContext:
    def __init__(self, repo: Path, *, window_start: dt.date, window_end: dt.date):
        self.repo, self.window_start, self.window_end = repo, window_start, window_end
        self._race_cards_cache: dict[dt.date, list[dict] | None] = {}
        self._session_index: dict[str, list[dt.date]] | None = None
        self._runs_cache: dict[tuple[str, dt.date], dict[int, list[str]]] = {}

    def race_cards_for(self, day: dt.date) -> list[dict] | None:
        if day not in self._race_cards_cache:
            self._race_cards_cache[day] = read_race_cards(self.repo, day)
        return self._race_cards_cache[day]

    def _build_session_index(self) -> dict[str, list[dt.date]]:
        """{場: [開催日(昇順), ...]}。窓 − 90 日 〜 窓の終了日 − 1 日 を 1 回だけ走査。"""
        earliest = self.window_start - dt.timedelta(days=MOTOR_HISTORY_LOOKBACK_DAYS)
        latest = self.window_end - dt.timedelta(days=1)
        index: dict[str, list[dt.date]] = {s: [] for s in STADIUMS}
        d = earliest
        while d <= latest:
            rows = self.race_cards_for(d) or []
            for s in {r["レースコード"][8:10] for r in rows}:
                index[s].append(d)
            d += dt.timedelta(days=1)
        return index

    def sessions_for(self, target_day: dt.date, stadium: str) -> list[list[dt.date]]:
        """detect_sessions と同じ結果を、ファイルを開かずに返す。"""
        if self._session_index is None:
            self._session_index = self._build_session_index()
        cutoff = target_day - dt.timedelta(days=MOTOR_HISTORY_LOOKBACK_DAYS)
        return group_sessions([d for d in self._session_index[stadium]
                               if cutoff <= d < target_day])

    def _extract_runs_for_session_cached(self, stadium: str, session_end: dt.date):
        key = (stadium, session_end)
        if key not in self._runs_cache:
            rows = self.race_cards_for(session_end) or []
            self._runs_cache[key] = extract_runs_for_session(rows, stadium)
        return self._runs_cache[key]

    def motor_history(self, day: dt.date) -> dict:
        """load_motor_history(repo, day) と同じ結果を返す。"""
        out = {}
        for stadium in STADIUMS:
            per_motor: dict[int, list] = defaultdict(list)
            for session in self.sessions_for(day, stadium):
                runs_by_motor = self._extract_runs_for_session_cached(stadium, session[-1])
                for m, runs in runs_by_motor.items():
                    per_motor[m].append(runs)
            for m, sessions in per_motor.items():
                out[(stadium, m)] = sessions[:MOTOR_HISTORY_SESSIONS]
        return out
```

`extract_runs_for_session(rows, stadium)` は、節最終日の `race_cards` からその場の各モーター番号について 14 スロットの
着順を集める関数で、素朴版と Context で共通です(本文では省略)。素朴版の `load_motor_history` は `detect_sessions` で得た
各節の最終日について `read_race_cards` を呼び直してから同じ関数に渡します。

これを合成データで動かしました。24 場それぞれが「4〜6 日開催 → 3〜8 日休み」を繰り返す日程を乱数で作り、
1 場 1 日あたり 2 レースぶんの行を書いた `race_cards` を 2025-07-24 から 2026-04-30 まで 281 ファイル用意します。
窓は 2025-11-01 〜 2026-04-30 の 181 日で、窓の全日について素朴版の `load_motor_history` と `ctx.motor_history` を呼び、
open 回数・時間・結果の一致を確認します。

```bash
$ python3 bench_feature_context.py
synthetic repo: 281 race_cards files, 2025-07-24 .. 2026-04-30
window: 2025-11-01 .. 2026-04-30 (181 days)
FeatureContext : open=      270  time=   0.18s  race_cards_cache=270 runs_cache=2306
naive          : open=  430,038  time=  44.97s
theoretical detect checks: 181 x 24 x 90 = 390,960
parity OK: 181 days, 220,797 (day, stadium, motor) entries identical
```

読み取れることを整理します。

- Context の 270 回は「181 日 + 90 日の遡り − 1」で設計書の見積もりどおりです。対象日ごとの処理はインデックスの list を
  絞るだけで、ファイルを 1 つも開きません。素朴版の 430,038 回は、存在チェック 390,960 回(181 × 24 × 90)に節最終日の
  読み直し約 39,000 回を足したもので、設計書の「約 410,000 回」と同じ構造です
- `runs_cache=2306` が設計書の約 1,350 より多いのは、合成日程が実際の開催カレンダーより節が多く(90 日に 8〜10 節)、
  現行実装の上限 10 節で数えているためです
- 結果は 220,797 件の `(日, 場, モーター)` すべてで一致しました
- 45 秒対 0.18 秒という時間差は、1 ファイル 2〜48 行の小さな合成データを stdlib の `csv` で読んだ場合の値で、
  本番の比率(75 分 → 10〜15 分)とは別物です。本番ではキャッシュで消えない pandas のメインループなどが残るため、
  比率は小さくなります

:::message
この計測は、設計書の見積もりが「回数」の水準で正しいことを確かめるためのものです。実時間の見積もりは
本番のファイルサイズと pandas の挙動に依存するので、合成データの秒数を根拠にはできません。
回数は構造から決まり、時間は環境で決まります。設計の段階で信頼できるのは前者です。
:::

## 元資料

- boatracecsv [`docs/design/feature_context_refactor.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/feature_context_refactor.md) — 観測ログ、根本原因の I/O 内訳、設計、テスト戦略、性能見積、ロールアウト計画、リスク、却下した代替案
- boatracecsv [`scripts/boatrace/index_features.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/index_features.py) — `FeatureContext` クラス、`compute_features_for_day`、`detect_sessions` / `load_motor_history` / `extract_runs_for_session`(旧経路)
- boatracecsv [`scripts/build_weights.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_weights.py) — `build_training_table` での Context の配線とキャッシュ統計のログ
- boatracecsv [`scripts/tests/unit/test_feature_context.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/tests/unit/test_feature_context.py) — parity テスト
- boatracecsv [`infra/run-monthly-weights.sh`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-monthly-weights.sh) — `git diff --cached --quiet` による冪等な commit
- boatracecsv [`docs/infrastructure.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md) — monthly-weights の実測所要時間(FeatureContext 導入後)、Job のタイムアウト設定

## 演習

公開 CSV `https://boatracecsv.github.io/data/programs/race_cards/YYYY/MM/DD.csv` を 1 か月ぶん
(例: 2026 年 8 月の 31 日)ローカルに保存し、次の 2 つを実装して「ファイルを開いた回数」を比べてください。

1. ファイルを読む関数に、呼び出し回数を数えるデコレータ `count_opens` を付ける
2. 素朴版 `detect_sessions(repo, stadium, target_day)` を遡り日数 30 日で書き、8 月 31 日を対象日として 24 場ぶん呼び、open 回数を記録する
3. `{場コード: [開催日, ...]}` のインデックスを 1 回の走査で作り、同じ 24 場ぶんの節を求めて open 回数を記録する。2 と結果が一致することも確認する

デコレータの骨格だけ示します。

```python:ex06_count_opens.py
import functools

def count_opens(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        wrapper.calls += 1
        return fn(*args, **kwargs)
    wrapper.calls = 0
    return wrapper

@count_opens
def read_race_cards(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))
```

素朴版は 24 場 × 30 日 = 720 回、インデックス版は 30 回前後になるはずです。余裕があれば対象日を 8 月 2 日から
31 日まで動かして合計を比べてください。自分の特徴量関数にも同じデコレータを付けて「呼び出しパターンごと」に
回数を数える習慣が、この章の 75 分を未然に防ぎます。
