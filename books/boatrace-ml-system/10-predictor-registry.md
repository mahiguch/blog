---
title: "予想者レジストリと A/B 実験"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 1 成分だけを差し替えて control と比べる実験設計、control を固定し続ける理由、退役判定の基準(有意な回収率差)、負けた予想者から「どの成分が悪かったか」を切り分ける方法、回収率では決着しない比較を別の指標に移す判断 |
| システム | 予想者を 1 つの frozen dataclass で宣言するレジストリ、追加は 1 エントリ・退役は `status` の変更だけ、退役後も ID を再利用しない規約、`active_predictors()` を唯一の参照点にして index 生成・重み学習・GCS ミラーを自動追従させる構造、Python と TypeScript の 2 リポジトリ間で ID を同期する運用 |

第 4 章から第 7 章で作った特徴量と重み学習は、そのままでは「1 つの予想」しか出せません。
新しい特徴量を思いついたとき、今の予想を上書きしてしまうと、良くなったのか悪くなったのかを
比べる相手がいなくなります。この章では、boatracecsv が複数の予想を **予想者(predictor)**
という単位で並行運用し、A/B 比較で採否を決めてきた仕組みを説明します。
数値は特に断りがない限り **2026 年 8 月時点**の実測値で、母数 n を添えます。

## 1. 予想者(predictor)という単位

### 1.1 なぜ予想を「差し替え」ではなく「並走」させるのか

boatracecsv の予想は、第 7 章で見たとおり「成分(偏差値化した特徴量)を場別の重みで
線形結合した強さポイント」です。成分の組み合わせを 1 つ決めれば 1 つの予想ができます。
この「成分の組み合わせ + 運用上のメタ情報」を 1 セットにしたものが予想者です。

予想者を分ける動機は、実験設計にあります。boatracecsv では次の 2 点を原則にしています。

1. **control を固定する**。最初の予想者 `v1_basic`(5 成分)は 2026-05-01 の投入以来ずっと
   `active` で、すべての実験の比較対象です。control 自身を改良してしまうと、
   過去の実験結果と比べられなくなります
2. **1 回の実験で差し替える成分は 1 つ**にする。たとえば `v4_motor` は control の
   `motor` を `motor4` に替えただけ、`v6_course` は `waku` を `course` に替えただけです。
   差し替えが 1 つなら、回収率に差が出たとき原因を 1 つに絞れます

この原則を破った例外が `v7_aggregate`(3 仮説の全部入り)で、その帰結は第 4 節で見ます。

### 1.2 PredictorSpec の宣言

レジストリの単一情報源は `scripts/boatrace/predictors/registry.py` です。
本質だけを抜き出すと次のようになります(実装からの抜粋。エントリは 3 つに絞っています)。

```python:registry.py(簡略版)
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

# 成分キー → CSV 列名に使う日本語ラベル。新成分はまずここに登録する。
COMPONENT_LABELS_REGISTRY: dict[str, str] = {
    "waku": "枠番pt", "racer": "選手pt", "motor": "モーターpt",
    "exhibit": "展示pt", "weather": "気象pt",
    "tenkai": "展開優位pt", "motor2rate": "モーター2連率pt",
    "motor4": "モーターpt", "course": "コースpt",
}

STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"


@dataclass(frozen=True)
class PredictorSpec:
    """1 予想者の宣言的定義。"""
    predictor_id: str            # 退役後も再利用しない
    display_name: str
    slot: int                    # active な予想者の表示順
    status: str                  # "active" か "retired"
    started_at: dt.date          # 累計回収率の起点
    component_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in (STATUS_ACTIVE, STATUS_RETIRED):
            raise ValueError(f"Unknown status {self.status!r} for {self.predictor_id!r}")
        if not self.component_keys:
            raise ValueError(f"predictor {self.predictor_id!r} has no component_keys")
        seen: set[str] = set()
        for key in self.component_keys:
            if key not in COMPONENT_LABELS_REGISTRY:
                raise ValueError(f"Unknown component key {key!r} in {self.predictor_id!r}. "
                                 "Register it in COMPONENT_LABELS_REGISTRY first.")
            if key in seen:
                raise ValueError(f"Duplicate component key {key!r} in {self.predictor_id!r}")
            seen.add(key)

    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def index_csv_path(self, repo: Path, day: dt.date) -> Path:
        return repo / "data" / "estimate" / self.predictor_id / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}.csv"

    def resolve_weights_csv_path(self, repo: Path, day: dt.date) -> Path | None:
        """day の月以下で最新の YYYY-MM.csv。当月ぶんが無ければ過去月にフォールバック。"""
        weights_dir = repo / "data" / "estimate" / "stadium" / "weights" / self.predictor_id
        if not weights_dir.exists():
            return None
        candidates = [p for p in sorted(weights_dir.glob("????-??.csv")) if p.stem <= f"{day:%Y-%m}"]
        return candidates[-1] if candidates else None


PREDICTORS: tuple[PredictorSpec, ...] = (
    PredictorSpec("v1_basic", "A君予想", 1, STATUS_ACTIVE, dt.date(2026, 5, 1),
                  ("waku", "racer", "motor", "exhibit", "weather")),
    PredictorSpec("v6_course", "コース予想", 6, STATUS_RETIRED, dt.date(2026, 7, 22),
                  ("course", "racer", "motor", "exhibit", "weather")),
    PredictorSpec("v10_kimarite", "穴予想", 10, STATUS_ACTIVE, dt.date(2026, 8, 13),
                  ("waku", "racer", "motor", "exhibit", "weather")),
)


def active_predictors() -> tuple[PredictorSpec, ...]:
    """status == "active" の予想者を slot 昇順で返す。"""
    return tuple(sorted((p for p in PREDICTORS if p.is_active()), key=lambda p: p.slot))


def predictor_by_id(predictor_id: str) -> PredictorSpec:
    for p in PREDICTORS:
        if p.predictor_id == predictor_id:
            return p
    raise KeyError(f"Unknown predictor_id: {predictor_id!r}")
```

設計上のポイントを順に説明します。

**frozen dataclass にする理由**。`PredictorSpec` はモジュール読み込み時に評価される定数で、
実行中に書き換わることを想定していません。`frozen=True` にしておくと、
うっかり `spec.status = "retired"` と書いたコードは `FrozenInstanceError` で落ちます。
退役はソースコードを変更してデプロイする行為であって、実行時の状態遷移ではない、
という意図を型で表しています。

**`component_keys` はタプル**。順序が index CSV の列順に対応するため、集合ではなく
順序つきの不変列にしています。`__post_init__` で重複も弾くので、実質「順序つき集合」です。

**`__post_init__` が守るもの**。検証は 4 つで、いずれも「レジストリの読み込み時点で落とす」
ことが目的です。

| 検証 | 落とさなかった場合に起きること |
| --- | --- |
| `status` が `active` / `retired` 以外 | `active_predictors()` の対象から静かに漏れる |
| `component_keys` が空 | 重み学習で 0 成分の回帰を解こうとして意味のない結果になる |
| 未登録の成分キー | CSV 列名(`component_label()`)の解決で `KeyError` になるのが、日次バッチの途中 |
| 重複した成分キー | 同名の列が 2 つできて、下流(fun-site)の列名解決が壊れる |

第 12 章で扱う「沈黙する失敗」の多くは、設定の誤りが**実行時の奥のほう**で顕在化することから
起きます。レジストリで検証すれば、誤った `PredictorSpec` はモジュールの `import` で例外になるので、
ユニットテストはもちろん、Cloud Run Jobs の起動直後に分かります。

scratchpad で動作を確認した結果を載せておきます。

```
active: [('v1_basic', 1), ('v10_kimarite', 10)]
ValueError: Unknown status 'paused' for 'v11_test'
ValueError: predictor 'v11_test' has no component_keys
ValueError: Unknown component key 'st_gap' in 'v11_test'. Register it in COMPONENT_LABELS_REGISTRY first.
ValueError: Duplicate component key 'waku' in 'v11_test'
FrozenInstanceError cannot assign to field 'status'
data/estimate/v1_basic/2026/08/31.csv
data/estimate/stadium/weights/v1_basic/2026-08.csv
data/estimate/stadium/weights/v1_basic/2026-09.csv
```

最後の 2 行は `resolve_weights_csv_path` の結果です。2026-08-31 に対しては `2026-08.csv`、
まだ重みが作られていない 2027-01 に対しては最新の `2026-09.csv` が返ります。
月次の重み学習(第 7 章)が回っていない月でも index 生成が止まらないよう、
「対象月以下で最新」の規則をここに置いています。同じ規則を GCS ミラーも使い、
「その日の index CSV を作ったのと同じ重みファイル」を fun-site に配ります。

### 1.3 `active_predictors()` を唯一の参照点にする

レジストリを持つ最大の利点は、消費側が「今どの予想者が動いているか」を自分で判断しなくなることです。
boatracecsv では次の 4 か所がすべて `active_predictors()` をループします。

| 消費側 | 処理 | 該当コード |
| --- | --- | --- |
| 日次バッチ | 朝の index 生成(`--mode daily`) | `build_index.py --all-active` |
| 直前バッチ | 締切 5 分前の index 更新(realtime 行の upsert) | `preview-realtime.py` |
| 月次バッチ | 場別重みの学習 | `build_weights.py --all-active` |
| GCS ミラー | index CSV と weights CSV の `csv_type` 生成 | `gcs_publisher.py` |

![レジストリと 4 つの消費側](/images/boatrace-ml-system/10-registry-consumers.png)
<!-- 図: 中央に registry.py(PREDICTORS タプル、active_predictors())。右に 4 つの消費側(build_index --all-active / preview-realtime / build_weights --all-active / gcs_publisher)が矢印で active_predictors() を参照。左下に fun-site predictors.ts が predictor_id で結ばれ、Pub/Sub の csv_type=index:{id} が GCS ミラーから fun-site へ流れる。infra/run*.sh の ACTIVE_PREDICTORS 配列は点線で「手動同期」と注記。 -->

`build_index.py` と `build_weights.py` の CLI は同じ形で、`--predictor` と `--all-active` が
排他になっています。対象予想者を解決する関数は 2 つのスクリプトで同一です。

```python:build_index.py(抜粋)
def _resolve_predictors(
    args_predictor: str | None, all_active: bool,
) -> list[PredictorSpec]:
    """``--predictor`` / ``--all-active`` の組合せから対象予想者を解決する。"""
    if all_active:
        if args_predictor:
            sys.exit("--predictor and --all-active are mutually exclusive")
        actives = active_predictors()
        if not actives:
            sys.exit("No active predictors in registry; nothing to do.")
        return list(actives)
    return [predictor_by_id(args_predictor or DEFAULT_PREDICTOR_ID)]
```

`--predictor` を省略すると `v1_basic` になるのは後方互換のためで、本番のジョブはすべて
`--all-active` で呼びます。つまり、新しい予想者を `PREDICTORS` に 1 エントリ足すだけで、
翌朝の日次バッチから index が生成され、直前バッチで更新され、翌月 1 日に重みが学習され、
GCS に配られます。

## 2. 運用ルール

### 2.1 退役は `status` を変えるだけ

予想者を止めるときは、該当エントリの `status` を `"retired"` に変えるだけです。
エントリ自体、過去の index CSV(`data/estimate/{id}/…`)、成分定義、計算ロジックは残します。
たとえば `tenkai` の計算関数 `tenkai_yui_pt()` は `v3_tenkai` の退役後も
`index_features.py` に常駐していますし、`course` のテーブル `course_win_rate.csv` は
消費者がいなくなった現在も月次で再生成が続いています。

削除しない理由は 2 つあります。

- 累計回収率の集計(第 17 章)は退役した予想者の過去データも参照します。
  ファイルを消すと、退役前の成績が「なかったこと」になります
- 退役した成分を作り直して再挑戦する可能性があります。`course` は 2026-08-09 に不採用と
  なりましたが、設計書には「時間減衰つき」「2 着率テーブル化」などの将来課題が残されており、
  そのときに計算ロジックがあれば差分だけ書けます

退役が `active_predictors()` からの除外を意味するので、第 1.3 節の 4 つの消費側は
自動的に対象から外します。`v9_suji` の直前バッチ側の買い目生成コードも、
`active_predictors()` に `v9_suji` が含まれるかを条件にしているため、
コードを消さずに停止しています。

### 2.2 ID は退役後も再利用しない

`predictor_id` は `<バージョン>_<特徴>` 形式で、退役した ID は二度と使いません。
理由は **累計回収率の同一性**です。fun-site は `started_at` を起点に、その ID の買い目が
的中したかどうかを日々積み上げて回収率を表示します。もし `v2_tenkai` の ID を
別のレシピで再利用すると、古いレシピと新しいレシピの成績が同じ数字に混ざります。

実際に `v2_tenkai` は、投入当初(2026-05-30〜06-13)は展開優位pt を加えた 6 成分版でしたが、
control を下回ったため 2026-06-13 に `motor` を `motor2rate` に替えた 5 成分版へレシピを変えました。
このときは ID を据え置く代わりに `started_at` を 06-13 にリセットして、累計を当日から計り直しています。
「ID を変えずに `started_at` をリセットする」のはこの 1 回だけで、以後は「レシピが違えば
新しい ID」に統一されました。`v3_tenkai` が `v2_tenkai` の 6 成分版と同じ内容で
別 ID になっているのはそのためです。

### 2.3 fun-site の `predictors.ts` と ID を同期する

配信側の fun-site(第 13 章・第 14 章)にも同じ形のレジストリ `packages/shared/src/predictors.ts` があります。
fun-site は `predictor_id` を使って CSV パス `data/estimate/{predictor_id}/YYYY/MM/DD.csv` を解決し、
Pub/Sub メッセージの `csv_type=index:{predictor_id}` を予想者に紐づけます。
つまり両リポジトリで **ID が一致していることが配信の前提**です。

```ts:packages/shared/src/predictors.ts(抜粋)
export type ComponentKey =
  | "waku" | "racer" | "motor" | "exhibit" | "weather"
  | "tenkai" | "motor2rate" | "motor4" | "course";

export type PredictorStatus = "active" | "retired";

export type PredictorSpec = {
  readonly id: string;                       // registry.py の predictor_id と同期
  readonly displayName: string;
  readonly slot: number;
  readonly status: PredictorStatus;
  readonly startedAt: string;                // YYYY-MM-DD。累計回収率の起点
  readonly componentKeys: readonly ComponentKey[];
  readonly useEstimatedST?: boolean;         // v5_slit / v7_aggregate: 予測 ST を AI 推定 ST に
  readonly strengthOnlyBetting?: boolean;    // v8_aionly: 買い目候補を強さpt のみで選定
  readonly bettingStyle?: "formation" | "suji" | "kimarite";  // v9 / v10: 買い目を CSV から読む
};

export function activePredictors(): readonly PredictorSpec[] {
  return PREDICTORS.filter((p) => p.status === "active").toSorted((a, b) => a.slot - b.slot);
}
```

Python 側と見比べると、TypeScript 側にだけあるフィールドが目につきます。
`useEstimatedST` / `strengthOnlyBetting` / `bettingStyle` は、**index や強さpt には影響せず、
買い目の作り方や表示にだけ効く差分**です。`v5_slit` は control と成分が完全に同一で、
違いは fun-site が 1 マーク走行距離の計算に使う予測 ST だけでした。この差分は Python 側の
`component_keys` では表現できないので、TypeScript 側のフラグとして持っています。
逆に、fun-site の `icon` や `showsAiPanels` のような表示専用のフィールドは Python 側に対応物がありません。
同期が必要なのは `id` / `slot` / `status` / `startedAt` / `componentKeys` で、表示名は各リポジトリの都合で
独立しています(2026-09 時点で `v1_basic` は registry.py では「A君予想」、fun-site では「本命予想」です)。

### 2.4 手動同期が残っている場所

自動追従には 1 つ例外があります。Cloud Run Jobs の起動スクリプト `infra/run.sh` /
`run-daily-sync.sh` / `run-monthly-weights.sh` にある `ACTIVE_PREDICTORS` 配列です。

```bash:infra/run-daily-sync.sh(抜粋)
ACTIVE_PREDICTORS=(v1_basic v10_kimarite)   # registry の active_predictors() と同期

for predictor in "${ACTIVE_PREDICTORS[@]}"; do
  sparse_paths+=("data/estimate/${predictor}/${TODAY_YM}")
done
git sparse-checkout init --cone
git sparse-checkout set "${sparse_paths[@]}"

commit_and_push_index() {
  for predictor in "${ACTIVE_PREDICTORS[@]}"; do
    git add "data/estimate/${predictor}/"
  done
  ...
}
```

これがシェルにある理由は、順序の問題です。第 11 章で説明するとおり、ジョブは
リポジトリを **sparse-checkout で部分的に clone** してから Python を動かします。
どのディレクトリを checkout するかは Python が動く前に決まっていなければならず、
その時点では `registry.py` を読めません。生成物の `git add` も同じ配列で回します。

したがって新しい予想者を投入するときの変更箇所は 3 つになります。

1. `registry.py` の `PREDICTORS` にエントリを追加(必要なら `COMPONENT_LABELS_REGISTRY` に成分ラベル)
2. `infra/run*.sh` の `ACTIVE_PREDICTORS` 配列
3. fun-site の `predictors.ts`

2 を忘れると、Python は新しい予想者の index を正しく生成するのに、cone-mode の sparse-checkout が
そのパスを持たないため生成物が**無言で捨てられます**。実際に `data/estimate/{suji,kimarite}/tables/` は
導入時から checkout 対象と `git add` の両方から漏れており、2026-08-22 に修正するまで永続化されて
いませんでした。この種の失敗は第 12 章で改めて扱います。

:::message
`ACTIVE_PREDICTORS` の行末コメントには、投入・退役のたびに日付と理由が追記されています。
レジストリと二重管理になっている以上、「なぜこの配列がこの値なのか」をシェル側にも
残しておく方が、次に触る人が registry.py と突き合わせやすいためです。
:::

## 3. v1〜v10 の系譜(2026-08 時点)

ここまでの仕組みで、2026-05 から 2026-08 の 4 か月間に 10 の予想者が投入されました。
表の「差」は control(`v1_basic`)と**同一レースで突き合わせた**回収率の差(ポイント)、
p はペア並べ替え検定の値です。検定の方法は第 9 章で説明したものと同じで、
直前(realtime)の買い目が組めた確定レースだけを対象に、各予想者の `started_at` 以降で
control と同じレースをペアにし、ペア bootstrap 20,000 反復の 95% 信頼区間と、
1 レースあたり収支差のペア並べ替え検定を行っています。p は 5 検定の Holm 補正前の値です。

| ID | 表示名 | control との差分(仮説) | 投入 | 退役 | n | 差 | p |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `v1_basic` | 本命予想(registry.py では「A君予想」) | control。waku, racer, motor, exhibit, weather の 5 成分 | 05-01 | active | — | — | — |
| `v2_tenkai` | B君予想 | `motor` → `motor2rate`(公式モーター 2 連対率) | 06-13 | 07-19 | — | 有意差なし | — |
| `v3_tenkai` | 展開予想 | `tenkai`(進入変更の有利度)を 6 成分目に追加 | 06-20 | 07-19 | — | 有意差なし | — |
| `v4_motor` | モーター予想 | `motor` → `motor4`(エキスパート評価でチューニング) | 07-20 | 08-10 | 3,035 | +0.30pt | 0.884 |
| `v5_slit` | スリット予想 | 成分は同一。予測 ST を AI 推定 ST に(fun-site 側フラグ) | 07-21 | 08-10 | 3,035 | −2.72pt | 0.377 |
| `v6_course` | コース予想 | `waku` → `course`(場 × レース番号 × コースの 1 着率) | 07-22 | 08-09 | 3,002 | −6.91pt | 0.0047 |
| `v7_aggregate` | 統合予想 | v4 + v5 + v6 の全部入り(`course` + `motor4` + AI 推定 ST) | 07-23 | 08-09 | 2,717 | −7.76pt | 0.0040 |
| `v8_aionly` | AI予想 | v7 と同一成分。買い目候補の選定を強さpt のみに | 07-28 | 08-09 | 1,892 | −10.62pt | 0.0001 |
| `v9_suji` | スジ予想 | 成分は同一。買い目をスジ表から生成(穴予想 A案) | 08-12 | 08-22 | 1,511 | (対 v10、回収率では判定せず) | — |
| `v10_kimarite` | 穴予想 | 成分は同一。買い目を決まり手モデルから生成(穴予想 B案) | 08-13 | active | — | — | — |

- 日付はすべて 2026 年です
- `v2_tenkai` / `v3_tenkai` の退役は「control に対して有意な回収率差が得られなかった」と
  記録されていますが、n や p の値は元資料に残っていません
- `v9_suji` の n = 1,511 は control ではなく `v10_kimarite` との同一レース数です(第 5 節)

系譜を眺めると、仮説の出どころが 3 種類あることが分かります。

**成分の差し替え(v2, v4, v6)**。第 5 章のモーター指数は、おかぺん評価(平和島の公開モーター評価)との
順位相関が着順ベースの `motor` でほぼ 0、公式 2 連対率で ρ ≒ 0.6 だったことから `v2_tenkai` が生まれました。
`v4_motor` はエキスパート評価 4 場との場別 Spearman 加重平均が +0.581 から +0.620 に改善した
パラメータ(スコア表 v4・ペナルティ −50・直近 5 節)を採用しています。`v6_course` は
場 × 季節のテーブルを場 × レース番号に替えたもので、テーブル単体では Brier 0.6485 → 0.6349、
log-loss 1.3535 → 1.3316 と較正が改善していました(train 2025-11〜2026-06 / test 2026-07)。

**成分の追加(v3)**。`tenkai` はスタート展示の進入コースと枠番のコース勝率差で、
「進入で前に行けた艇は有利」という仮説を 6 成分目として足しました。

**成分は同一で、買い目の作り方だけを変える(v5, v8, v9, v10)**。index も強さpt も control と
同値で、fun-site 側のフラグや別 CSV で買い目だけが変わります。`v5_slit` は第 18 章の ST 推定を
予測 ST に使い、`v8_aionly` は買い目候補の選定から予測 ST を外し、`v9` / `v10` は第 21 章の
穴予想です。同一成分の予想者は重み(第 7 章)も同値になるので、投入初月は control の
weights ファイルをコピーしてブートストラップし、翌月から `--all-active` に任せます。

どの種類の仮説も、設計書の「限界・リリース判断」の節に同じ文が書かれています。
`v4_motor` の設計書は「エキスパート評価との相関改善 ≒ 回収率改善ではない」、
`v6_course` の設計書は「ホールドアウト改善 ≒ 回収率改善ではない」と述べ、
どちらも「独立スロットとして投入し、累計回収率で control と A/B 比較してから判断する」と
結んでいます。`v2` / `v3` の教訓(相関 ρ ≒ 0.6 でも回収率で勝てなかった)を、
以後の予想者の採否基準として明文化した形です。

## 4. 負け方を分析する

2026-08-09 の判定で 3 つの予想者が同時に退役しました。検定の全体は次のとおりです
(2026-08 時点、直前買い目・確定レースのみ)。

| 予想者 | n | 回収率 | control | 差 | 95% CI | p(並替) | Holm 補正 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `v6_course` | 3,002 | 79.06% | 85.97% | **−6.91pt** | [−13.1, −0.5] | 0.0047 | 0.016 |
| `v7_aggregate` | 2,717 | 78.10% | 85.86% | **−7.76pt** | [−13.9, −1.7] | 0.0040 | 0.016 |
| `v8_aionly` | 1,892 | 77.30% | 87.92% | **−10.62pt** | [−18.5, −2.9] | 0.0001 | 0.0005 |
| (参考)`v4_motor` | 3,035 | 85.97% | 85.66% | +0.30pt | [−2.4, +3.6] | 0.884 | 0.884 |
| (参考)`v5_slit` | 3,035 | 82.95% | 85.66% | −2.72pt | [−7.0, +1.2] | 0.377 | 0.755 |

control の回収率が行ごとに違う(85.66〜87.92%)のは、ペアにするレース集合が各予想者の
`started_at` で変わるためです。同一レースで比較する以上、control 側の数字も予想者ごとに計算し直します。

### 4.1 有意差が「本物」かを確かめる

負けたという結論を出す前に、元資料では 3 つの頑健性チェックをしています。

- **外れ値依存ではないか**。差分の大きい上位 20 レースを除外しても差はほぼ不変でした。
  3 連単は 1 レースの高配当が集計を左右するので、このチェックは必須です
- **日単位でも一貫しているか**。control を下回った日が `v6_course` は 17/20 日(符号検定 p = 0.0026)、
  `v8_aionly` は 13/13 日(p = 0.0002)でした。特定の数日に負けが集中しているのではありません
- **買い目の点数のせいではないか**。3 者は control より買い目点数が多く(`v6` は 13.0 点 vs 11.6 点、
  `v8` は 14.7 点 vs 11.7 点)、点数が多いほど購入額が増えて回収率は下がりやすくなります。
  そこで点数分布を control に揃えて標準化しても、回収率は 76〜78%(`v6` は 77.5%)にとどまりました。
  点数ではなく、**選定そのもの**の問題です

### 4.2 共通差分で原因を絞る

3 者のレシピを control と並べると、共通しているのは `waku` → `course` の差し替えです
(`v7` / `v8` はそれに `motor4` も加わります)。一方、`course` を持たない `v4_motor` / `v5_slit` は
control と同水準(+0.30pt / −2.72pt、どちらも有意差なし)です。第 1.1 節の「差し替えは 1 つ」の原則が
ここで効きます。`v7_aggregate` 単独では 3 仮説のどれが寄与したか分離できませんが、
同時期に走っていた単独スロットの結果を並べることで、**`course` の持ち込みが主因**と判断できました。

負け方の中身も記録されています。的中率だけは `v6` / `v7` / `v8` の方が高く(46.8〜48.9% vs 46.1〜46.6%)、
`v6` 単独でも 46.8% vs 46.1% でした。当たっているのに回収率が低いのは、
**堅い決着は当てるが、安いオッズを厚く買って期待値を落とす**負け方です。
`course` テーブルの改善は「12R はイン(1 コース)が強い」という情報をモデルに足すものでしたが、
その情報はオッズにも織り込まれていると考えられ、的中率の上昇分が配当の低下で相殺された、
というのが設計書の解釈です。テーブル単体では Brier / log-loss とも改善していたので、
**較正の改善が回収率に乗らなかった**ことになります。

### 4.3 結論の重みを正しく見積もる

ただし、この分析には限界も明記されています。

- 3 者は `course` を共有しているため、3 つの検定は**独立ではありません**。3 回否定したのではなく、
  実質「`course` 仮説を 1 回否定した」重みで扱う必要があります
- 観測期間は 13〜20 日と短く、n も 1,892〜3,002 レースです。95% CI の下限は −0.5pt まで伸びています

`v7_aggregate` については、もう 1 つ教訓があります。3 仮説を束ねた総合スロットは
「効果が直交していれば足し合わさる」見込みで投入されましたが、`v4` の +0.30pt と `v5` の −2.72pt を
加えても `course` の −6.91pt は打ち消せず、全体として −7.76pt になりました。
悪い成分が 1 つあれば全部入りは沈みます。単独スロットが結果を出す前に全部入りを走らせると、
負けたときに切り分けの材料が単独スロット側にしかない、ということです。

### 4.4 有意差なしの退役

翌 2026-08-10 に `v4_motor` / `v5_slit` も退役しました。こちらは「有意に悪い」ではなく
「有意差なし」による消極的な退役です。両者は control とレシピが近く(`v5` は成分が完全に同一、
`v4` は `motor` → `motor4` の 1 成分差)、実際に表示される買い目が control と大きく重なります。
似た買い目のスロットを並べても情報が増えないため、次の仮説を検証できるクリーンな状態
(active = control のみ)に戻すことを優先しました。

`v5_slit` には退役を後押しする独立の観測もありました。第 19 章で扱う逆算で、実測 ST から組んだ
スリット隊形は 1 着コースを強く規定する(強さpt に足して log loss −0.143)のに、締切前に取れる
ST ではその 12% しか回収できず、75% を取るには ST の MAE を 0.016 秒(現行 0.053 秒)まで
下げる必要があると分かっていました。予測 ST の精度改善という路線自体の投資対効果が低かったのです。

## 5. v9 の退役は成績劣化ではない

最後の退役は性質が違います。2026-08-22 に穴予想 A案 `v9_suji` が退役しましたが、
理由は **B案 `v10_kimarite` と穴予想スロットが重複した**ことで、成績の劣化ではありません。

本番の realtime 買い目(2026-08-13〜08-22、両案で同一の 1,511 レース)の実測は次のとおりです。

| | A案 `v9_suji` | B案 `v10_kimarite` |
| --- | ---: | ---: |
| 的中率 | 8.95% | 11.33% |
| 回収率 | 70.7% | 68.8% |
| 平均配当 | **3,949 円** | 3,035 円 |
| 万舟 | 10 本 | 5 本 |
| 万舟 / 1 万円 | **0.133** | 0.066 |

買い目の重なりは平均 2.70 点 / 5 点(完全一致 1.3%、1 着艇の集合一致 11.5%)で、
設計時のバックテストの 2.62 点と同水準でした。**買い目そのものは半分しか重ならないのに、
回収率では区別できません**。観測された差 +4.2pt を有意にするには約 34,700 レース(8.2 か月)が
必要で、差が 2pt なら 36 か月かかります。第 9 章の検出力の逆算が、ここでは「この比較は回収率では
決着しない」という判断に使われています。

そこで穴予想スロットの主判定は **3 連単 log-loss** に移しました。log-loss は n = 3,527 の時点で
効果の 5.8 倍の精度があり、回収率は「control 比 −7pt 級の劣化を検知するガードレール」としてだけ使います。
A案はスジ表(条件つき頻度表)から出目を選ぶだけで確率モデルを持たないため、log-loss に載りません。
確率モデルを持ち主判定に載る B案を残し、A案を退役させました。

ただし、**体験指標では A案が上回っています**。平均配当は 1.30 倍、万舟 / 1 万円は 2.0 倍です。
「穴らしさ」を優先するなら判断は逆になりえます。元資料はこの点を記録として残し、
再挑戦するなら退役した ID は再利用せず新しい ID を立てる、と結んでいます。

運用面では、`v9_suji` の退役で止めたのは日次の買い目生成(`build_suji_picks.py`)だけです。
月次で再生成する決まり手注釈テーブル(`kimarite_table.csv`)は `v10_kimarite` が読むので続いていますし、
`build_kimarite_picks.py` は `build_suji_picks.py` から関数を import しています。
「退役 = `status` の変更だけ、資産は残す」という第 2.1 節のルールが、ここでは
現役の予想者を守る形で効いています。

:::message
第 3 節の表を見返すと、退役の判定基準が 3 種類あることが分かります。
(1) control より有意に悪い(v6 / v7 / v8)、(2) control と有意差がなく買い目も重なる(v4 / v5)、
(3) スロットが重複し主判定が別指標に移った(v9)。「勝てなかったから退役」とひとくくりにせず、
どの基準で退役したかをレジストリのコメントに残しておくと、後から仮説を再検討するときの
出発点が違ってきます。
:::

## 元資料

- [scripts/boatrace/predictors/registry.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py) — レジストリ本体。冒頭コメントに各退役の検定結果
- [docs/data/estimate.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) — 予想者レジストリの仕様、現行レジストリ表、退役ノート、各予想者の特徴量説明
- [docs/design/course_strength_v6.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/course_strength_v6.md) — §6 限界・リリース判断、§9 実装時検証、末尾「結果: 2026-08-09 退役」
- [docs/design/aggregate_v7.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/aggregate_v7.md) — §4 control との比較観点、§5 経緯
- [docs/design/motor_score_tuning_v4.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/motor_score_tuning_v4.md) — §6 限界・リリース判断、§7 運用手順
- [docs/operations.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/operations.md) — 予想者の運用、v9_suji / v10_kimarite の運用と退役判定
- [scripts/build_index.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_index.py) / [scripts/build_weights.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_weights.py) — `--all-active` の解決
- [scripts/preview-realtime.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/preview-realtime.py) / [scripts/boatrace/gcs_publisher.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/gcs_publisher.py) — `active_predictors()` の消費側
- [infra/run-daily-sync.sh](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-daily-sync.sh) / [infra/run.sh](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run.sh) / [infra/run-monthly-weights.sh](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-monthly-weights.sh) — `ACTIVE_PREDICTORS` 配列
- [fun-site packages/shared/src/predictors.ts](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/predictors.ts) — TypeScript 側のレジストリ(詳細は第 14 章)

## 演習

新しい予想者を registry に追加し、1 日分の index を生成して、レジストリの自動追従を確かめます。
boatracecsv のローカル clone を前提にします(index 生成には公開 CSV に加えて重みファイルと
90 日分の出走表が要るため、clone が最も簡単です)。

1. 環境を作ります。

   ```bash
   git clone https://github.com/BoatraceCSV/boatracecsv.github.io.git
   cd boatracecsv.github.io
   python -m venv .venv && source .venv/bin/activate
   pip install -r scripts/requirements.txt
   ```

2. `scripts/boatrace/predictors/registry.py` の `PREDICTORS` タプル末尾に、control と同じ 5 成分の
   予想者を追加します。成分が同じなら重みも control と同値になるので、重みファイルは
   コピーでブートストラップできます(`v5_slit` / `v9_suji` / `v10_kimarite` の投入時と同じ手順です)。

   ```python
   PredictorSpec(
       predictor_id="v11_exercise",
       display_name="演習予想",
       slot=11,
       status=STATUS_ACTIVE,
       started_at=dt.date(2026, 8, 31),
       component_keys=("waku", "racer", "motor", "exhibit", "weather"),
   ),
   ```

   ```bash
   mkdir -p data/estimate/stadium/weights/v11_exercise
   cp data/estimate/stadium/weights/v1_basic/2026-08.csv data/estimate/stadium/weights/v11_exercise/
   ```

3. レジストリが新しい予想者を返すことを確認します。`slot` 昇順で 3 件になるはずです。

   ```bash
   cd scripts && python -c "from boatrace.predictors import active_predictors; print([p.predictor_id for p in active_predictors()])"
   cd ..
   ```

4. 1 日分の index を生成します。過去日の backfill は `--mode realtime` で、`--out` を指定して
   `data/` の外に書きます。

   ```bash
   python scripts/build_index.py --date 2026-08-31 --mode realtime \
       --predictor v11_exercise --out /tmp/v11_2026-08-31.csv
   ```

   出力の末尾に `(weights: 2026-08.csv)` と表示されれば、`resolve_weights_csv_path` がコピーした
   重みを解決しています。`(no weights file → 強さpt is NaN)` と出たら手順 2 のコピー先を確認してください。

5. 生成した CSV の強さpt の列を `data/estimate/v1_basic/2026/08/31.csv` の同じ列と比べてください。
   成分と重みが同一なので、値が一致するはずです。「成分は同一で買い目だけが違う」予想者
   (v5 / v8 / v9 / v10)が、index の段階では control と見分けがつかないことを確認できます。

6. 追加課題: `component_keys` に未登録のキー(たとえば `"st_gap"`)を入れて手順 3 を実行し、
   どの時点でどんなメッセージで落ちるかを確かめてください。次に `status="paused"` でも試してください。
   どちらも `import` の時点で `ValueError` になり、`build_index.py` までは到達しません。

7. 本番に投入する場合に残る変更箇所を挙げてください(第 2.4 節)。`infra/run*.sh` の `ACTIVE_PREDICTORS` に
   `v11_exercise` を足さないと何が起きるか、sparse-checkout と `git add` の 2 段階に分けて説明してください。
