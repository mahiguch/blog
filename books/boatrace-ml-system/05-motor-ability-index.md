---
title: "モーター能力指数: z 残差・時間減衰・ベイズ収縮"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | セル内標準化(z 残差)で交絡を除く、指数時間減衰(半減期)と Kish の有効サンプル数、事前分布へのベイズ収縮、正解データがないときにエキスパート評価を代理指標にして検証する方法、中間指標の改善が本番 KPI に乗らない例 |
| システム | 節境界の検出、モーター期起算日での履歴リセット、フィーチャーフラグによる算術等価性の保証、計算過程そのものを CSV で公開する設計 |

第 4 章で扱った 4 成分(枠番・選手・展示・気象)は、いずれも当日の CSV だけで素点が決まりました。モーターpt だけは違います。過去 90 日ぶん・全 24 場の出走履歴を舐め、そこから作ったベースラインで 1 走ずつ標準化し、時間で重みを付け、サンプル不足を補正して、ようやく 1 基ぶんの素点が出ます。この章はその計算をひととおり追い、最後に「エキスパート評価でパラメータを調整したら中間指標は改善したのに回収率は変わらなかった」という結果までを扱います。

## 1. 問題: モーターの良し悪しをどう測るか

ボートレースのモーターは場に紐づく共有機材で、選手は節ごとに抽選で割り当てられたモーターに乗ります(第 1 章)。公式サイトはモーターごとに「2 連対率」を公開しており、これがもっとも手軽なモーター指標です。ただし 2 連対率には 2 つの交絡があります。

- **誰が乗ったか**: A1 級の選手が乗った節と B2 級の選手が乗った節では、同じモーターでも着順が変わります。
- **どのコースだったか**: 1 コースの 1 着と 6 コースの 1 着は価値が違います(1 コースの 1 着率は 5 割を超えます)。

最初の実装(本書では v1 と呼びます)は、直近 5 節の着順を「級別 × グレード分類」の得点表で点数化して平均する、というものでした。得点表は `data/estimate/motor_ability_score.csv` に外出しした 6 行の CSV で、B2 級の 1 着は 125 点、A1 級の一般戦 1 着は 50 点、といった具合に「弱い選手で勝ったモーターを高く評価する」ように設計されています。

```csv:motor_ability_score.csv
級別,グレード分類,1着pt,2着pt,3着pt,4着pt,5着pt,6着pt
B2,全,125,100,75,50,25,0
B1,全,100,80,60,40,20,0
A2,SG_G1,125,100,75,50,25,0
A2,G2_G3_一般,75,60,45,30,15,0
A1,SG_G1,100,80,60,40,20,0
A1,G2_G3_一般,50,40,30,20,10,0
```

この v1 指数がどれくらい「モーターの良し悪し」を捉えているかを、正解データを使って確かめたのが `notebooks/motor_pt_okapen_validation.ipynb` です。正解にしたのはボートレース平和島が公開している「おかぺんモーター評価」(機番ごとの SS〜E の 11 段階グレード)で、2026 年 5 月 12〜16 日の節の前検評価 40 機を使いました。結果は次のとおりです(Spearman ρ、n=40)。

| 説明変数 | Spearman ρ |
| --- | ---: |
| 公式 3 連対率 | +0.608 |
| 公式 2 連対率 | +0.600 |
| 当時のモーターpt | **−0.050** |

着順ベースの指数はおかぺん評価とほぼ無相関で、公式 2 連対率のほうがはるかによく合っていました。この結果を受けて、着順ベースの `motor` を公式 2 連対率 `motor2rate` に差し替えた予想者 `v2_tenkai` が 2026-06-13 に投入されます(第 10 章)。しかし `v2_tenkai` は control(`v1_basic`)に対して有意な回収率差が出ず、2026-07-19 に退役しました。「おかぺん評価との相関が高い」ことと「回収率が上がる」ことは別だ、という教訓がここで 1 つ得られています。

一方で着順ベースの指数そのものも、上の 2 つの交絡を明示的に扱うように作り直されました。それが本章の主題であるモーター能力指数 v2 です。v2 の設計書は v1 のスコア表・トークン分類・節検出を引き継いだうえで、次の 3 点を追加しています。

1. **コース補正 + SD 標準化**: 級別 × グレード × 進入コースのセルごとに平均と標準偏差を取り、生得点を z 残差 `(raw − μ_cell) / σ_cell` に直す。
2. **時間減衰**: 半減期 60 日の指数減衰で直近の走を重く見る。
3. **ベイズ収縮**: サンプル不足のモーターを事前平均(z 残差 0)へ縮める。

:::message
本文の回収率・順位相関などの実測値は、特記がない限り 2026 年 8 月時点のものです。
:::

## 2. 1 走レコードと節の検出

### 2.1 入力データ

v2 は `results` ではなく `programs/race_cards`(出走表)を主データにします。出走表には各艇について「節間成績」として最大 14 スロット(7 日 × 2 走)の `艇N_節D{D}走{S}_着順` / `_進入` / `_枠` が入っていて、これを使うと結果 CSV には無い `転`(転覆)/ `落`(落水)/ `沈`(沈没)/ `エ`(エンスト)といった事故トークンまで区別できます。あわせて `programs/title` から節の開催グレード、`programs/motor_stats` から「モーター期起算日」を読みます。

| ソース | 取得項目 | 利用可能開始日 |
| --- | --- | --- |
| `programs/race_cards/YYYY/MM/DD.csv` | `艇N_モーター番号`、`艇N_級別`、`艇N_節D{D}走{S}_{着順,進入,枠}` | 2025-05-03 |
| `programs/title/YYYY/MM/DD.csv` | `グレード` | 2026-05-01 |
| `programs/motor_stats/YYYY/MM/DD.csv` | `モーター期起算日` | 2026-04-25 |

1 走ぶんのレコードは `MotorRun` という frozen dataclass です。v1 では着順だけでしたが、v2 で `race_date`(時間減衰用)と `lane`(コース補正用)が加わりました。

```python:index_features.py(抜粋)
@dataclass(frozen=True)
class MotorRun:
    session_end: dt.date   # 当該走を含む節の最終開催日
    stadium: str           # "01"〜"24"
    motor_num: int         # 物理モーター番号
    grade_bucket: str      # "SG_G1" / "G2_G3_一般" / "全"
    racer_class: str       # "A1" / "A2" / "B1" / "B2"
    finish: str            # 正規化済 着順トークン
    race_date: dt.date | None = None    # None → session_end でフォールバック
    lane: int = 0                        # 0 → コース補正対象外
```

### 2.2 節境界を検出する

「直近 N 節」を取り出すには節の境界が要りますが、`title` の日次列は title CSV が存在しない過去日には使えません。そこで `detect_sessions()` は、**同じ場で連続して開催されている日(日差 1 日以内)を 1 節として束ねる**という機械的な規則で節を検出します。当日から 90 日(`MOTOR_HISTORY_LOOKBACK_DAYS`)遡って `race_cards` にその場のレースコードが含まれる日を集め、古い順に並べて連続日を束ね、新しい順に最大 10 節(`MOTOR_HISTORY_LOOKBACK_MAX_SESSIONS`)返します。

```python:index_features.py(抜粋)
def detect_sessions(repo, stadium, window_end, max_sessions=10, window_days=90):
    open_days = []
    for back in range(1, window_days + 1):        # window_end 当日は含めない
        d = window_end - dt.timedelta(days=back)
        if _has_races_at(repo, d, stadium):
            open_days.append(d)
    open_days.sort()                              # 古→新
    sessions, cur = [], []
    for d in open_days:
        if not cur or (d - cur[-1]).days <= 1:    # 連続日なら同じ節
            cur.append(d)
        else:
            sessions.append(cur); cur = [d]
    if cur:
        sessions.append(cur)
    return sessions[-max_sessions:][::-1]         # 新→旧
```

ポイントは `range(1, …)` で**当日を除外している**ことです。当日のレースは未来情報なので履歴に入れてはいけません。副作用として「今節の走りは素点に反映されない」ことになり、`節 = 0` は常に前回の節を指します。節の途中に中止日が 1 日挟まっても「日差 ≤ 1」で同じ節にまとまります。

各節について `extract_runs_for_session()` は**節最終日の `race_cards` だけ**を読みます。節間成績はその節の全走を含むので、最終日の 1 ファイルで節全体が取れます。同じモーターが同じ節の複数レースに現れても、`motor_rows` 辞書の先勝ちで 1 回しか読みません。スロット `D{D}走{S}` の実日付は `session_start + (D − 1)` 日で復元し、`lane` は `_進入` を優先して欠損なら `_枠` を使います(進入が 9 割は枠と一致しますが、実際に展開を決めるのは進入コースだからです)。

### 2.3 モーター期起算日で履歴をリセットする

同じ「場 × モーター番号」でも、期切替やモーター交換が行われれば物理的に別のモーターです。`load_motor_history()` は `motor_stats` の `モーター期起算日` を読み、**節最終日が起算日より前の節を履歴から落とし**、残った節を新しい順に 6 節(`MOTOR_HISTORY_SESSIONS`)まで採用します。10 節まで多めに集めておくのは、この剪定で削られるぶんの保険です。起算日が見つからないモーター(`motor_stats` に収録されていない場など)はフィルタせず全節を採用する、というフェイルセーフになっています。

期切替直後で履歴が 0 節のモーターは素点が NaN になり、下流の偏差値化で 50(平均)に補完されます。履歴が 1〜2 節しかないモーターは NaN にはなりませんが、後述のベイズ収縮で平均寄りに引き戻されます。

![モーターpt の計算パイプライン](/images/boatrace-ml-system/motor-pt-pipeline.png)
<!-- 図: 左から右へ「race_cards 節間成績(14 スロット)→ detect_sessions で節に束ねる → 期起算日で剪定し 6 節 → MotorRun 列」、その下に「全 24 場の MotorRun をプールしてセル μ/σ(baseline)」、右側で「1 基の MotorRun 列 → z 残差 → 減衰重み w → Σw, Σwz, Σw² → n_eff → 収縮 → 素点 → 場別偏差値化(第 4 章)」。当日は履歴に含まれないことを×印で示す -->

## 3. z 残差: 誰が乗っても比べられるようにする

### 3.1 セルごとの μ と σ

第 1 節の 2 つの交絡(級別とコース)を、v2 は「同じ条件の走どうしで比べる」ことで除きます。条件とは `(級別, グレード分類, 進入コース)` の組み合わせで、これをセルと呼びます。`compute_lane_baseline()` は当日の履歴ウィンドウに入っている**全 24 場・全モーターの MotorRun** をこのセルに分け、セルごとに生得点の母集団平均 μ と母集団標準偏差 σ を計算します。1 走のスコアは生得点そのものではなく、そのセルでの z 残差になります。

```
z_i = (raw_i − μ_cell) / σ_cell
```

2026-08-22 の実データ(`estimate/motor_pt/baseline/2026/08/22.csv`)から A1 級・一般戦のセルを抜くと次のようになっています。

| 級別 | グレード分類 | 進入 | μ | σ | サンプル数 |
| --- | --- | ---: | ---: | ---: | ---: |
| A1 | G2_G3_一般 | 1 | 44.58 | 11.71 | 2,736 |
| A1 | G2_G3_一般 | 2 | 33.49 | 16.41 | 2,008 |
| A1 | G2_G3_一般 | 6 | 21.72 | 16.39 | 1,407 |
| B1 | 全 | 1 | 69.81 | 32.91 | 3,667 |
| B1 | 全 | 6 | 25.05 | 25.89 | 3,942 |

A1 の一般戦は 1 着が 50 点なので、1 コースのセル平均 44.58 は「A1 が 1 コースならほぼ勝つ」ことを表しています。ここで 1 着を取っても z = (50 − 44.58) / 11.71 ≈ +0.46 にしかならない一方、6 コースから 1 着を取れば z = (50 − 21.72) / 16.39 ≈ +1.73 です。逆に 1 コースで 6 着(0 点)は z ≈ −3.81 と大きなマイナスになります。**平均を引くことでコースと級別の期待値を除き、σ で割ることでセル間の分散の違いを揃える**、という 2 段の補正です。

セルのサンプルが 5 本未満(`LANE_BASELINE_MIN_SAMPLES`)なら `(級別, グレード分類)` のセルにフォールバックし、それも無ければ `(μ, σ) = (0, 1)`(補正なし)にします。σ には下限 10(`LANE_BASELINE_SD_FLOOR`)を置き、全走が同点になった退化セルで z が暴発するのを防いでいます。この 3 段のフォールバックが `cell_stats()` です。

### 3.2 事故トークンの扱い

選手pt(第 4 章)は「機材事故は選手の責任ではない」として事故走を除外しますが、モーターpt は逆です。`転` / `落` / `沈` / `エ` は機材の欠陥や整備不良を示唆するので、**生得点 −100(`MOTOR_NEGATIVE_SCORE`)として分母にも乗せます**。一方 `F`(フライング)/ `L`(出遅れ)/ `失` / `妨` は選手起因なので分子にも分母にも乗せず、`欠` / `不` も走が成立していないので除外します(`MOTOR_SKIP_TOKENS`)。この非対称は意図的なもので、定数として明示されています。

2026-08-22 の `runs` CSV(19,470 走)を数えると事故トークンは `転` 63 / `落` 18 / `エ` 17 / `沈` 1 の計 99 走、全体の 0.5% です。件数は少ないですが 1 走あたりの影響は大きく、−100 という値が妥当かどうかは v1 設計書の未決事項として残されていました。この話は第 6 節で戻ってきます。

### 3.3 副作用: スコア表の行の高さは消える

セル内標準化には 1 つ見落としやすい副作用があります。スコア表の各行(級別 × グレード分類)は、いま「B2 は 125 点満点、A1 一般は 50 点満点」のように高さが違いますが、セルは行の中に含まれるので、**行全体を何倍しても z 残差は変わりません**。つまり v1 で「弱い選手で勝ったモーターを高く評価する」ために置いた行間の差は、v2 では原理的に効かなくなります。効くのは行の中での着順ごとの間隔の形だけです。数式は第 6.3 節で示します。

## 4. 時間減衰と有効サンプル数

### 4.1 半減期 60 日

モーターは整備で調子が変わるので、3 か月前の走と先週の走を同じ重さで平均するのは不自然です。v2 は各走に指数減衰の重みを付けます。

```
w_i = exp(−ln2 × days_ago_i / 60) = 0.5 ^ (days_ago_i / 60)
```

`days_ago` は「計算対象日 − 走行日」の日数で、60 日前の走は 0.5、120 日前は 0.25 の重みです。半減期 60 日は「6 節(1 節はおおむね 30 日弱の間隔)で 6 節目の寄与が 13% 程度まで薄れる」という設計値で、v1 の 5 節を 6 節に増やしたのは減衰で末尾が自然に軽くなるからです。2026-08-22 の `runs` では減衰重みの最小値が 0.354、最大値が 0.977 でした(90 日ルックバックの範囲に収まっています)。

### 4.2 Kish の有効サンプル数

重み付き平均を使うと「何走ぶんの証拠があるか」が単純な走数では表せなくなります。40 走あっても大半が 0.4 の重みなら、等重みの 40 走より情報量は少ないはずです。これを表すのが Kish の有効サンプル数です。

```
n_eff = (Σw)² / Σw²
```

全部の重みが 1 なら n_eff = N(走数)になり、1 走だけが極端に重ければ n_eff は 1 に近づきます。実装ではループの中で `Σw`、`Σ(w·z)`、`Σw²` の 3 つの累積和を持つだけで、n_eff と加重平均の両方が出ます。2026-08-22 の `motors` CSV(567 基)では走数の平均 34.3 に対して n_eff の平均は 32.8 で、減衰による情報量の目減りはこの時点ではわずかでした。

## 5. ベイズ収縮

### 5.1 サンプル不足を事前平均へ引き戻す

期切替直後のモーターや休場明けのモーターは走数が少なく、たまたま 1 着が続いただけで z 残差の平均が大きくなります。v2 はこれを「事前分布の平均 0(= 全モーターの平均)へ縮める」ことで抑えます。

```
素点 = n_eff / (n_eff + k) × Σ(w·z) / Σw        k = 10
```

k は「事前分布が何走ぶんの証拠に相当するか」です。n_eff = 10 なら加重平均を半分に、n_eff = 30 なら 3/4 に縮めます。n_eff が大きくなるほど係数は 1 に近づき、十分に走ったモーターはほとんど縮められません。事前平均を 0 にできるのは、第 3 節でセル内標準化を済ませているので z 残差が構造的に 0 中心だからです。この 3 段(z 残差 → 減衰 → 収縮)はそれぞれ独立したフィーチャーフラグ(`ENABLE_LANE_CORRECTION` / `ENABLE_DECAY` / `ENABLE_SHRINKAGE`)を持ち、**全 OFF + 5 節にすると v1 の単純平均と算術等価**になることをユニットテストで保証しています。段階リリースと ablation のための設計です。

![収縮係数 n_eff/(n_eff+k)](/images/boatrace-ml-system/motor-shrinkage-curve.png)
<!-- 図: 横軸 n_eff(0〜60)、縦軸 収縮係数 n_eff/(n_eff+k)(0〜1)。k=0(常に 1)、k=10(採用値、n_eff=10 で 0.5)、k=50 の 3 本の曲線。2026-08-22 実データの n_eff の中央値 34.6 に縦の点線 -->

### 5.2 簡略版コード

以下は実装(`motor_ability_breakdown()`)から本質だけを抜いた簡略版です。関数名・定数名は実装に合わせてあります。「1 走レコードのリスト → セル z 残差 → 半減期 60 日の重み → Kish n_eff → k = 10 収縮 → 素点」の流れが 1 本の関数に収まっています。

```python:motor_ability_simplified.py
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass

DECAY_HALF_LIFE_DAYS = 60.0
DECAY_LAMBDA = math.log(2) / DECAY_HALF_LIFE_DAYS        # ≈ 0.01155
LANE_BASELINE_MIN_SAMPLES = 5
LANE_BASELINE_SD_FLOOR = 10.0
SHRINKAGE_PRIOR_K = 10.0
MOTOR_NEGATIVE_TOKENS = {"転", "落", "沈", "エ"}         # 機材起因 → ペナルティ
MOTOR_NEGATIVE_SCORE = -100                               # v4_motor は -50
SCORE_TABLE = {  # data/estimate/motor_ability_score.csv と同じ内容
    ("B2", "全"):        [125, 100, 75, 50, 25, 0],
    ("B1", "全"):        [100,  80, 60, 40, 20, 0],
    ("A2", "SG_G1"):     [125, 100, 75, 50, 25, 0],
    ("A2", "G2_G3_一般"): [75,  60, 45, 30, 15, 0],
    ("A1", "SG_G1"):     [100,  80, 60, 40, 20, 0],
    ("A1", "G2_G3_一般"): [50,  40, 30, 20, 10, 0],
}


@dataclass(frozen=True)
class MotorRun:
    """1 走レコード。race_cards の節間成績 1 スロットに対応する"""
    stadium: str        # "01"〜"24"
    motor_num: int
    racer_class: str    # "A1" / "A2" / "B1" / "B2"
    grade_bucket: str   # "SG_G1" / "G2_G3_一般" / "全"
    finish: str         # "1"〜"6" / "転" / "落" / "沈" / "エ" / "F" / ...
    race_date: dt.date  # 時間減衰の経過日数の起点
    lane: int           # 進入コース 1〜6(0 = 不明)


def bucket_of(run: MotorRun) -> str:
    return run.grade_bucket if run.racer_class in ("A1", "A2") else "全"


def score_motor_run(table, run: MotorRun, negative_score=MOTOR_NEGATIVE_SCORE):
    """生得点。None は「分母にも乗らない」(F/L/失/妨/欠/不)"""
    pts = table.get((run.racer_class, bucket_of(run)))
    if pts is None:
        return None
    if run.finish in ("1", "2", "3", "4", "5", "6"):
        return pts[int(run.finish) - 1]
    if run.finish in MOTOR_NEGATIVE_TOKENS:
        return negative_score
    return None


def _mu_sigma(scores):
    """母集団 μ, σ。σ は下限 10 で丸める(退化セルでの z 暴発防止)"""
    mu = sum(scores) / len(scores)
    var = sum((x - mu) ** 2 for x in scores) / len(scores)
    return mu, max(math.sqrt(var), LANE_BASELINE_SD_FLOOR)


def compute_baselines(all_runs, table):
    """全 24 場の全走から (級別, グレード, 進入) セルと (級別, グレード) セルの μ/σ を作る"""
    lane_cells, cg_cells = defaultdict(list), defaultdict(list)
    for run in all_runs:
        raw = score_motor_run(table, run)
        if raw is None:
            continue
        cg_cells[(run.racer_class, bucket_of(run))].append(raw)
        if run.lane >= 1:
            lane_cells[(run.racer_class, bucket_of(run), run.lane)].append(raw)
    lane_baseline = {k: _mu_sigma(v) for k, v in lane_cells.items()
                     if len(v) >= LANE_BASELINE_MIN_SAMPLES}
    class_grade_avg = {k: _mu_sigma(v) for k, v in cg_cells.items()
                       if len(v) >= LANE_BASELINE_MIN_SAMPLES}
    return lane_baseline, class_grade_avg


def cell_stats(lane_baseline, class_grade_avg, cls, grade, lane):
    """フォールバック階層: 進入セル → 級別×グレード → (0, 1) = 補正なし"""
    if lane >= 1 and (cls, grade, lane) in lane_baseline:
        return lane_baseline[(cls, grade, lane)]
    return class_grade_avg.get((cls, grade), (0.0, 1.0))


def motor_ability_pt(runs, table, lane_baseline, class_grade_avg,
                     target_day: dt.date, k: float = SHRINKAGE_PRIOR_K) -> dict:
    """1 基ぶんの 1 走レコード列から素点を計算する(戻り値は内訳つき)"""
    sum_w = sum_wr = sum_w2 = 0.0
    for run in runs:
        raw = score_motor_run(table, run)
        if raw is None:
            continue
        mu, sigma = cell_stats(lane_baseline, class_grade_avg,
                               run.racer_class, bucket_of(run), run.lane)
        z = (raw - mu) / sigma                                   # セル z 残差
        days_ago = max(0, (target_day - run.race_date).days)
        w = math.exp(-DECAY_LAMBDA * days_ago)                   # 半減期 60 日
        sum_w += w
        sum_wr += w * z
        sum_w2 += w * w
    if sum_w == 0.0:
        return {"n_eff": 0.0, "mean_resid": float("nan"), "raw_pt": float("nan")}
    n_eff = sum_w * sum_w / sum_w2                               # Kish の有効サンプル数
    mean_resid = sum_wr / sum_w
    raw_pt = n_eff / (n_eff + k) * mean_resid                    # prior 平均 0 へ収縮
    return {"n_eff": n_eff, "mean_resid": mean_resid, "raw_pt": raw_pt}
```

実装との違いは、履歴を `{(場, モーター番号): [節ごとの MotorRun 列]}` という二重リストで受け取る代わりに 1 基ぶんの平らなリストを受け取ること、フィーチャーフラグを省いたこと、ベースライン 2 種類を 1 関数にまとめたことだけです。同じ合成データを実装の `motor_ability_breakdown()` に通して、素点が誤差 0 で一致することを確認しています。

### 5.3 合成データで k を変えてみる

ベースライン用に 200 基 × 30 走の母集団を作り、性格の違う 4 基を用意して k = 0 / 10 / 50 の素点を比べます。

```python:demo_synthetic.py(抜粋)
cases = {
    "好調(40 走 / 90 日)":  make_runs("04", 1, 40, 90, +0.8),
    "新モーター(4 走 / 5 日, 全 1 着)":
        [MotorRun("04", 2, "A1", "G2_G3_一般", "1", TODAY - dt.timedelta(days=d), 3)
         for d in (2, 3, 4, 5)],
    "平均的(35 走 / 90 日)": make_runs("04", 3, 35, 90, 0.0),
    "平均的 + 転覆 1 回":    make_runs("04", 4, 35, 90, 0.0)
        + [MotorRun("04", 4, "A1", "G2_G3_一般", "転", TODAY - dt.timedelta(days=3), 2)],
}
for name, runs in cases.items():
    res = {k: motor_ability_pt(runs, SCORE_TABLE, lane_baseline, class_grade_avg, TODAY, k=k)
           for k in (0, 10, 50)}
```

```
ケース                              n_eff  mean_z     k=0    k=10    k=50
好調(40 走 / 90 日)                  36.5   0.359   0.359   0.282   0.152
新モーター(4 走 / 5 日, 全 1 着)       4.0   1.620   1.620   0.463   0.120
平均的(35 走 / 90 日)                32.7  -0.184  -0.184  -0.141  -0.073
平均的 + 転覆 1 回                   33.1  -0.436  -0.436  -0.335  -0.174
```

見どころは 2 行目です。4 走すべて 1 着の新モーターは、収縮なし(k = 0)では加重平均 z = 1.62 で「好調」の 4 倍以上の評価になります。k = 10 では n_eff ≈ 4 なので 4/14 ≈ 0.29 倍に縮められ 0.463 になりますが、それでも 36 走ぶんの証拠がある「好調」の 0.282 を上回っています。k = 50 まで強めると順位が逆転します。k は「何走ぶんの平均的な証拠と釣り合わせるか」を決める値で、大きくするほど実績の少ないモーターに慎重になる代わりに、実績が十分なモーターの差も潰れます。2026-08-22 の実データ(565 基)で素点の標準偏差を再計算すると k = 0 で 0.281、k = 10 で 0.188、k = 50 で 0.094 と、k を上げるにつれ分布全体が平均へ寄っていきます。

4 行目は −100 ペナルティの効き方です。35 走の平均的なモーターに転覆を 1 回足すだけで、加重平均 z は −0.18 から −0.44 へ動きました。1 走で 0.25 ぶん動くのは、他の走が ±1 前後の z に収まっているのに対し、転覆の生得点 −100 が、この合成データの A1 一般・進入 2 のセル(μ ≈ 25、σ ≈ 17)では z ≈ −7.4 に相当するからです。実データでも A1 一般のセルは σ が 12〜17 程度(第 3.1 節の表)なので、事故 1 走が z で −7〜−12 のオーダーになる点は同じです。

## 6. エキスパート評価でチューニングする(v4_motor)

### 6.1 正解データと目的関数

v1 設計書には「スコア表は根拠なく決めている」「−100 ペナルティの妥当性は未検証」という未決事項が残っていました。これをデータで決め直したのが 2026-07-19 の `motor_score_tuning` です。モーターの良し悪しには「正解ラベル」がありません。そこで、場の公式サイトが公開しているモーター評価をエキスパートの判断として正解に据えました。4 場・計 183 機の単一時点スナップショットです。

| 場 | 評価 | n |
| --- | --- | ---: |
| 04 平和島(おかぺん) | SS〜E の 11 段階 | 43 |
| 23 唐津 | 素性 S〜D の 5 段階 | 60 |
| 24 大村 | 評価平均 1〜7 点 | 70 |
| 14 鳴門 | 金 / 銀 / 銅(上位 10 機のみの打ち切りラベル) | 10 |

目的関数は場別 Spearman ρ のラベル数加重平均です。各場の評価集計期間の末尾に合わせた `target_day` で `load_motor_history()` を実行し、全 24 場の走レコード(各時点で約 5.9 万走)を前計算しておき、スコア表の形状・ペナルティ・半減期・k・節数・lane 補正の有無を引数に取る numpy ハーネスで素点を再計算します。ハーネスは現行構成で本番実装と最大誤差 7e-15 で一致することを先に確認してあります。**探索の前に「探索用コードが本番と同じ答えを出す」ことを確かめる**のは、この種のチューニングで最初にやるべき手順です。

### 6.2 全探索は過学習し、頑健な 3 パラメータだけを採用する

まず現行(v2)の位置を確認します。

| 構成 | 平和島 | 唐津 | 大村 | 鳴門 | 加重平均 |
| --- | ---: | ---: | ---: | ---: | ---: |
| v2(現行 motor) | +0.623 | +0.590 | +0.589 | +0.290 | **+0.581** |
| (参考)公式 2 連対率のみ | +0.660 | +0.386 | +0.600 | +0.338 | +0.530 |
| **v4(提案)** | **+0.656** | **+0.611** | **+0.641** | **+0.372** | **+0.620** |

第 1 節で「相関ほぼ 0」だった着順ベースの指数は、v2 化(z 残差 + 減衰 + 収縮)を経て加重平均 +0.581 に達し、公式 2 連対率単体(+0.530)をすでに上回っていました。平和島単独では 2 連対率のほうが高い(+0.660 vs +0.623)ものの、唐津では大差で逆転しています。

次に、スコア表の 36 値と行別の形状・スケールまで自由に振る Optuna の 3,000 試行の全探索を行うと、加重平均は +0.629 まで上がります。ところが leave-one-stadium-out(LOSO: 3 場で選んだ構成を残り 1 場で評価)にかけると、平和島を隠したときの評価が +0.589 と現行の +0.623 を下回りました。行ごとの形状差やスケール差は 1 枚のスナップショットのノイズを拾っている、つまり過学習です。

そこで、1 次元の感度分析で「どの場でも同じ方向に効く」パラメータだけを拾いました。

- ペナルティ: −100 → −20〜−50 で全場改善。−200 は大幅に悪化。γ = 1.5 との組み合わせでは −50 が最適
- スコア表の形状 γ(全行一律の凸カーブ `pt(k) = round(A × ((6 − k) / 5)^γ)`): 1.3〜1.6 に山。0.8 以下の凹型は明確に悪化
- 節数: 5 > 6 > 4
- 収縮 k: 0〜10 でフラット、20 以上で悪化(Optuna が選んだ k = 41 はノイズ)
- 半減期: 40〜60 に山。減衰 OFF は悪化
- lane 補正 OFF: 加重平均 −0.034(平和島は −0.14)

採用したのは γ = 1.5、ペナルティ −50、節数 5 の 3 つだけで、半減期 60 日・k = 10・lane 補正 ON は据え置きです。この小さなグリッドで LOSO をやり直すと 4 場すべてで一貫して改善し(+0.017〜+0.084、加重平均 +0.037)、3 場学習で選ばれる構成も fold 間でほぼ同じ(γ = 1.5〜1.8、ペナルティ −50、5 節、半減期 60)でした。

| held-out | 調整後 | 現行 | 差 |
| --- | ---: | ---: | ---: |
| 平和島 | +0.653 | +0.623 | +0.030 |
| 唐津 | +0.607 | +0.590 | +0.017 |
| 大村 | +0.639 | +0.589 | +0.050 |
| 鳴門 | +0.374 | +0.290 | +0.084 |

こうしてできたのが v4 のスコア表です。行の高さ(1 着 pt)は据え置き、行の中だけ凸にして整数に丸めています(整数丸めによる劣化は +0.0005 で無視できます)。

```csv:motor_ability_score_v4.csv
級別,グレード分類,1着pt,2着pt,3着pt,4着pt,5着pt,6着pt
B2,全,125,89,58,32,11,0
B1,全,100,72,46,25,9,0
A2,SG_G1,125,89,58,32,11,0
A2,G2_G3_一般,75,54,35,19,7,0
A1,SG_G1,100,72,46,25,9,0
A1,G2_G3_一般,50,36,23,13,4,0
```

:::message
**−100 は過大だった。** v1 設計書のスコアリング節には、定数 `MOTOR_NEGATIVE_SCORE = -100` の横に「機材起因 → -20 点で打点」というコメントが残っています。設計中に −20 から −100 へ引き上げ、「事故 1 回が B2 級の 1 着 1 回分(+125)に拮抗するスケール」と説明したうえで、未決事項に「−50 / −100 / −150 などをパラメトリックに比較して選び直す余地あり」と書いていました。1 年近く経ってから実データで比較すると −20〜−50 の範囲が全場で良く、−50 は「事故 1 回 ≒ B2 の 2〜3 着 1 回分のマイナス」に相当します。転覆 1 回で評価が壊れすぎていた、というのが結論です。設計時に「決め打ちだ」と書き残しておいたことが、後で検証する動機になりました。
:::

### 6.3 なぜ行間スケールを据え置いたのか

第 3.3 節で予告した副作用を式で確かめます。スコア表の行 r(級別 × グレード分類)の得点を、行の高さ A_r と着順ごとの形 s(k) の積 `raw = A_r · s(k)` と書きます。セル(級別, グレード分類, 進入)は行 r の中に含まれるので、セル内の全走が同じ A_r を持ちます。

```
μ_cell = A_r · E[s]        σ_cell = A_r · SD[s]
z = (A_r · s(k) − A_r · E[s]) / (A_r · SD[s]) = (s(k) − E[s]) / SD[s]
```

A_r が分子と分母から消えるので、行の高さをいくら変えても z 残差は 1 つも動きません。効くのは形 s(k)(= γ)だけです。ただしペナルティ −100 は A_r に比例していないので、行の中での「ペナルティの相対的な深さ」`−100 / A_r` は残ります。これが「効くのは行内の間隔形状とペナルティの相対深さのみ」という設計書の記述の中身で、全探索が拾っていた行別スケールの差が原理的に意味を持たない(ノイズしか拾えない)ことも、この式から分かります。σ の下限 10 が効く退化セルでは厳密には消えませんが、実データではサンプル数の多いセルばかりなので影響はありません。lane 補正を将来 OFF にするなら A_r は再調整の余地が生まれます。

### 6.4 回収率では control と有意差なし

チューニング結果は現行の `v1_basic` のスコア表を書き換える形では反映しませんでした。`v1_basic` の意味を変えないため、v4 の表とペナルティ・節数を `motor4` という別成分にし、`motor` を `motor4` に差し替えただけの予想者 `v4_motor`(2026-07-20 開始)を独立スロットとして投入して、control と回収率で A/B 比較しています(第 10 章)。実装は v2 の計算式にキーワード引数を足しただけで、`score_motor_run(table, run, negative_score=-50)`、`motor_ability_pt(..., max_sessions=5)` のように差し替えます。本番コードパスの `motor4` 出力がチューニング用ハーネスと最大誤差 4e-15 で一致することも確認しました。

結果です。2026-08-09 に実施した、control と同一レースを突き合わせたペア比較(ペア bootstrap 20,000 反復の 95% CI とペア並べ替え検定、第 9 章)では、次のようになりました。

| 予想者 | n | 回収率 | control | 差 | 95% CI | p |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `v4_motor` | 3,035 | 85.97% | 85.66% | +0.30pt | [−2.4, +3.6] | 0.884 |

**+0.30pt、p = 0.884。** エキスパート評価との順位相関は +0.581 → +0.620 に上がったのに、回収率では何も言えない結果でした。`v4_motor` は 2026-08-10 に退役しています。「有意に悪い」わけではない消極的な退役ですが、motor → motor4 の 1 成分差では表示される買い目が control と大きく重なり、似た買い目のスロットを並べても情報が増えないため、次の仮説を検証するクリーンな状態に戻すことを優先しました。

これは本書で「中間指標の改善が本番 KPI に乗らない」最初の例です。理由として考えられるのは、(1) 正解が単一時点のスナップショットで節をまたいだ再現性が未検証だったこと、(2) モーターpt は強さポイントの 5 成分の 1 つにすぎず、重み(第 7 章)を通ると差が薄まること、(3) そもそも期間 3,035 レースでは ±3pt 程度の差しか検出できないこと(95% CI の幅)です。`v2_tenkai`(motor2rate)でも同じことが起きていたので、v4 設計書はあらかじめ「相関改善 ≒ 回収率改善ではない。累計回収率で A/B 比較してから最終判断する」と書いており、その手順どおりに退役しました。エキスパート評価は正解データが無いときの有用な代理指標ですが、代理指標での改善は本番 KPI で確認するまで改善と呼ばない、という運用です。

## 7. 計算過程を公開する

モーターpt の素点は、第 3 節のとおり全 24 場を横断したベースライン μ/σ に依存します。つまり **1 基ぶんの素点でも全場のコーパスが要ります**。当日ぶんの CSV しか取らない下流(fun-site、第 13 章)では、`race_cards`・`title`・`motor_stats` を全部揃えても再現できません。第 4 章の 4 成分は fun-site 側で検算できるのに、モーターpt だけは原理的にできない、という非対称がここで生まれます。

解決策は、計算過程そのものを派生データとして配ることです。日次バッチ `build_motor_pt_breakdown.py` が、その日の出走表に出てくる `(場コード, モーター番号)` について 3 つの CSV を `data/estimate/motor_pt/{runs,motors,baseline}/YYYY/MM/DD.csv` に書き出します。

| ファイル | 粒度 | 主な列 |
| --- | --- | --- |
| `runs` | 1 走 1 行 | 節 / 走行日 / 級別 / グレード分類 / 進入 / 着順 / 生得点 / セルμ / セルσ / 残差z / 減衰重み |
| `motors` | 1 基 1 行 | 節数 / 走数 / Σw / Σw2 / n_eff / 加重平均残差 / 素点 |
| `baseline` | 1 セル 1 行 | 級別 / グレード分類 / 進入(0 はフォールバック行)/ μ / σ / サンプル数 |

2026-08-22(13 場開催)の実測で 567 基 / 19,470 走 / 約 1.8MB です。`runs` の `セルμ` / `セルσ` はフォールバック解決後の値なので、下流は `runs` の行だけで `Σw → n_eff → 素点` を組み立て直せます。`motors` は採点対象の走が 1 本も無いモーターも 1 行出す(素点以下が空欄)ので、「ファイルに無い」と「履歴が無い」を区別できます。

設計上大事なのは、この明細を作るコードと素点を作るコードを分けなかったことです。`motor_ability_pt()` は `motor_ability_breakdown()` の `raw_pt` を返すだけの薄いラッパで、累算順序も同じなので、**index CSV のモーターpt と明細が食い違うことはありません**。丸めた CSV から再計算した素点は `motors` の `素点` と末尾の桁がずれますが(2026-08-22 の実測で最大 6.4e-7)、表示用途では無視できます。この 3 ファイルを fun-site が読んで「素点 → 偏差値pt → 寄与」を展開する検算ページを作る話は第 16 章で扱います。

運用上の注意も 2 つあります。素点は直近 6 節 = 過去 90 日ぶんの `race_cards` を舐めるので、2 分毎に走る直前バッチの checkout はそれを持ちません。そのため直前バッチはモーターpt を再計算せず、朝バッチが計算した `daily` 行の値を引き継ぎます(`DAILY_REUSED_COMPONENTS`)。当日を含む節は履歴に入らないので、引き継いでも値は変わりません。もう 1 つは sparse-checkout の範囲で、90 日窓が触る月ぶんの `race_cards` / `title` が checkout されていないと採用節数が落ち、**エラーにはならずにモーターpt が 50 側へ潰れます**。これは第 12 章で扱う「沈黙する失敗」の典型例です。全場横断の履歴を毎日組み立てる処理の高速化(セッションインデックスの事前計算とベースラインの日次キャッシュ)は第 6 章で扱います。

## 元資料

- [docs/design/motor_ability_index.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/motor_ability_index.md) — v1 設計(スコア表、トークン分類、節検出、期起算日での剪定)
- [docs/design/motor_ability_index_v2.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/motor_ability_index_v2.md) — v2 設計(時間減衰、コース補正、ベイズ収縮、フィーチャーフラグ)
- [docs/design/motor_score_tuning_v4.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/motor_score_tuning_v4.md) — v4 設計(エキスパート評価によるチューニングと v4_motor)
- [notebooks/motor_score_tuning/report.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/notebooks/motor_score_tuning/report.md) — チューニングの全記録(Optuna 全探索、感度分析、LOSO)
- [notebooks/motor_pt_okapen_validation.ipynb](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/notebooks/motor_pt_okapen_validation.ipynb) — おかぺん評価との順位相関スキャン
- [docs/data/motor_pt.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_pt.md) — 素点内訳 CSV(runs / motors / baseline)のスキーマ
- [docs/data/motor_ability_score.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_ability_score.md) — スコア表 CSV(現行と v4)
- [docs/data/estimate.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) — `N枠_モーターpt` の列定義、v4_motor の退役ノート
- [scripts/boatrace/index_features.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/index_features.py) — `MotorRun`、`detect_sessions`、`extract_runs_for_session`、`compute_lane_baseline`、`cell_stats`、`motor_ability_breakdown`、`motor_ability_pt`
- [scripts/boatrace/predictors/registry.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py) — `motor2rate` / `motor4` 成分と退役時の検定結果
- [scripts/build_motor_pt_breakdown.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_motor_pt_breakdown.py)、[scripts/boatrace/motor_pt_breakdown.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/motor_pt_breakdown.py) — 素点内訳の書き出しと `recompute_raw_pt()`
- [scripts/tests/unit/test_motor_ability_v2.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/tests/unit/test_motor_ability_v2.py) — v1 算術等価性を含むユニットテスト

## 演習

公開 CSV だけで解けます。2026-08-22 の素点内訳を使います。

- `https://boatracecsv.github.io/data/estimate/motor_pt/runs/2026/08/22.csv`
- `https://boatracecsv.github.io/data/estimate/motor_pt/motors/2026/08/22.csv`
- `https://boatracecsv.github.io/data/estimate/motor_pt/baseline/2026/08/22.csv`

1. `runs` を `(場コード, モーター番号)` でグループ化し、`減衰重み` と `残差z` から `Σw`、`Σw²`、`n_eff`、素点(k = 10)を再計算して、`motors` の `素点` との最大絶対差を求めてください。丸め誤差の範囲(1e-6 程度)に収まるはずです。
2. 同じ手順で k を 0 / 10 / 50 に変え、素点の標準偏差と、上位 10 基の顔ぶれがどう入れ替わるかを比べてください。走数(`motors` の `走数`)が少ないモーターほど k で順位が動くことを確かめてください。
3. `baseline` の `進入 = 1〜6` の行を級別ごとに並べ、μ がコースにどう依存するかを見てください。そのうえで `runs` から「進入 6 で 1 着」の走と「進入 1 で 1 着」の走を抜き、`残差z` の分布を比べてください。
4. (発展)`runs` の `減衰重み` を 1.0 に置き換えて(減衰 OFF)素点を再計算し、k = 10 のままで各モーターの素点がどれだけ動くかを調べてください。動きが大きいモーターは、どの時期に走が集中しているでしょうか。
