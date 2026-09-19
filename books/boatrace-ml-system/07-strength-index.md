---
title: "強さポイント: 非負制約付き最小二乗"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 線形モデルを制約付き最適化(SLSQP)で学習する、`w ≥ 0` と `Σw = 1` が「寄与への分解」と「偏差値スケールの維持」を同時に保証する仕組み、場ごとに別のモデルを学習する意味、R² の読み方と限界 |
| システム | 月次バッチ(Cloud Run Jobs)、重みファイルの解決規則(対象月以下で最新)、サンプル不足時のフォールバック、新しい予想者の重みをブートストラップする手順 |

第 4 章と第 5 章で、枠番・選手・モーター・展示・気象の 5 成分を「偏差値pt」に揃えました。この章では、それらを **1 本の数字「強さpt」にまとめる重み** をどう学習するかを扱います。

boatrace-fun.net の重み学習は、機械学習としてはごく単純です。特徴量 5 個の線形モデルを、`w ≥ 0` かつ `Σw = 1` という制約の下で最小二乗法で解くだけです。しかしこの 2 つの制約が、下流(買い目の生成、fun-site の「なぜ強いか」の表示、月次バッチの運用)を丸ごと単純にしています。「精度を上げるためのモデル」ではなく「運用と説明を成り立たせるためのモデル」として読んでください。

## 1. 目的変数と学習データ

### 学習窓は「対象月の前 6 か月」

重みは月に 1 回、予想者ごと・場ごとに学習します。対象月を `2026-08` とすると、学習窓は `[2026-02-01, 2026-07-31]` です。対象月自身のデータは含めません。含めると、8 月の予想に 8 月の結果が漏れ込む(リーケージ)からです。

```python:build_weights.py(抜粋)
target = parse_month(args.month)            # 2026-08-01
end = target - dt.timedelta(days=1)         # 2026-07-31
start = six_months_before(target)           # 2026-02-01
```

### 特徴量テーブルと結果の JOIN

`build_training_table()` は学習窓の 1 日ずつについて、第 4〜6 章の `compute_features_for_day()` で 1 艇 1 行の長形式テーブル(`レースコード, 枠番, waku, racer, motor, exhibit, weather, …`)を作り、`data/results/realtime/` の結果 CSV から `(レースコード, 枠番, 着順)` を作って inner join します。

結果 CSV は 1 レース 1 行で `1着_艇番, 2着_艇番, …, 6着_艇番` の横持ちなので、`load_results_for_day()` が 6 着ぶんをループして縦持ちに直します。艇番と枠番は同じ番号なので、`枠番` 列にそのまま入れます。艇番が取れない着(欠場・失格など)はスキップされ、その艇の行は JOIN で落ちます。

6 か月分の特徴量計算は素朴に書くと 75 分かかっていました。`FeatureContext` を学習窓全体で 1 つ作って `compute_features_for_day(repo, day, ctx=ctx)` に渡し、`race_cards` などの読み込みを共有することで 10〜15 分に縮めた経緯は第 6 章のとおりです。

学習テーブルは予想者に依存しません。`compute_features_for_day()` は登録済みの全成分列(`waku`, `racer`, `motor`, `motor4`, `course`, `tenkai`, …)を毎回出力するので、1 つのテーブルを `--all-active` の全予想者で使い回せます。予想者ごとに違うのは `component_keys`(どの列を使うか)だけです(第 10 章)。

### 目的変数: `7 − 着順` を標準化する

目的変数は着順そのものではなく `7 − 着順` です。1 着が 6、6 着が 1 になり、「大きいほど良い」向きに揃います。これを標準化して `y` とします。

```
y_raw = 7 − 着順
y     = (y_raw − μ_y) / σ_y
```

6 艇が揃ったレースなら `y_raw` の平均は 3.5、標準偏差は √(35/12) ≒ 1.708 です。実際の重みファイル(`weights/v1_basic/2026-08.csv`)の `mu_y` は 24 場すべてで 3.52〜3.55、`sigma_y` は 1.69〜1.70 で、理論値からわずかにずれています。欠場や失格で 5 艇以下になったレースがあるためで、この 2 列を見ると JOIN の欠けを検算できます。

着順を「間隔尺度」として扱っている点は、正直に言えば近似です。1 着と 2 着の差、5 着と 6 着の差が同じ 1 とは限りません。それでも回帰の目的変数に採用したのは、(1) 6 値の順序尺度に対して線形回帰は頑健で、(2) 買い目に使うのは強さpt の **レース内順位と差**(第 8 章)であって絶対値ではないからです。標準化しているので、`y` のスケールは重みの比率に影響しません。

学習テーブルの大きさは、2026-08 の重みファイルの `n_samples` 列を合計すると 24 場で 141,412 艇行、場ごとには 4,521 行(福岡)〜7,094 行(常滑)です。

## 2. 制約付き最小二乗

### 定式化

場ごとに、標準化済みの特徴量行列 `Z`(n 行 × 5 列)と目的変数 `y` について、次を解きます。

```
minimize    mean((Z·w − y)²)
subject to  w_k ≥ 0  (k = 1..5),   Σ_k w_k = 1
```

切片はありません。`Z` の各列と `y` はどちらも平均 0 に標準化してあるので、切片の最小二乗解は 0 になり、置く意味がないからです。

制約がなければ通常の最小二乗で閉じた解が出ますが、`w ≥ 0`(境界制約)と `Σw = 1`(等式制約)があるので数値最適化が要ります。実装は `scipy.optimize.minimize(method="SLSQP")` です。SLSQP(逐次二次計画法)は等式・不等式・境界を同時に扱える汎用の手法で、変数が 5 個、行が 6,000 前後ならミリ秒で収束します。目的関数は凸(二次)で制約は線形なので、局所解の心配もありません。

### 簡略版コード

以下は `scripts/build_weights.py` の `fit_one()` から本質だけを抜き出したものです。関数名と定数名は実装のままにしてあります。

```python:fit_weights.py
import numpy as np
import pandas as pd
from scipy.optimize import minimize

# 6 か月の学習窓全体では値が揃わない「短期成分」。欠損行を捨てずに z=0 で補完する
SHORT_HISTORY_COMPONENTS = frozenset({"motor", "motor4"})
MIN_SAMPLES = 60


def fit_weights(Z: np.ndarray, y: np.ndarray) -> np.ndarray:
    """minimize mean((Z·w − y)²)  s.t.  w ≥ 0,  Σw = 1"""
    k = Z.shape[1]

    def objective(w):
        return float(np.mean((Z @ w - y) ** 2))

    def grad(w):
        return 2.0 * Z.T @ (Z @ w - y) / len(y)

    constraints = ({"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},)
    res = minimize(objective, np.full(k, 1.0 / k), jac=grad, method="SLSQP",
                   bounds=[(0.0, 1.0)] * k, constraints=constraints,
                   options={"maxiter": 200, "ftol": 1e-9})
    w = np.clip(res.x, 0.0, None)          # 数値誤差で −1e-12 になった要素を 0 に
    return w / w.sum() if w.sum() > 0 else np.full(k, 1.0 / k)


def fit_one(df_st: pd.DataFrame, component_keys: tuple[str, ...]) -> dict:
    """1 場ぶんの重みを学習する。df_st は成分の素点列 + 着順 列を持つ長形式。"""
    n_components = len(component_keys)
    fallback_weight = 1.0 / n_components

    # 1. 成分ごとの μ, σ は「その列が欠損していない行」だけで求める
    mus, sigmas = {}, {}
    for k in component_keys:
        col = df_st[k].dropna()
        mus[k] = float(col.mean()) if len(col) else 0.0
        sigmas[k] = max(float(col.std(ddof=0)), 1e-9) if len(col) else 1.0

    # 2. fit に使う行 = 長期成分と着順が揃っている行。短期成分は μ で補完(z=0)
    long_history = [k for k in component_keys if k not in SHORT_HISTORY_COMPONENTS]
    sub = df_st.dropna(subset=long_history + ["着順"]).copy()
    sub = sub[(sub["着順"] >= 1) & (sub["着順"] <= 6)]
    for k in component_keys:
        if k in SHORT_HISTORY_COMPONENTS:
            sub[k] = sub[k].fillna(mus[k])
    n = len(sub)
    if n < MIN_SAMPLES:
        w = {k: fallback_weight for k in component_keys}
        return dict(mu=mus, sigma=sigmas, w=w, n_samples=n,
                    r2=float("nan"), fallback=True)

    # 3. 標準化: 特徴量は場別 (μ, σ)、目的変数は 7 − 着順 を標準化
    Z = np.column_stack([(sub[k].values - mus[k]) / sigmas[k] for k in component_keys])
    y_raw = (7 - sub["着順"].values).astype(float)
    y = (y_raw - y_raw.mean()) / max(y_raw.std(ddof=0), 1e-9)

    # 4. 制約付き最小二乗と R²
    w_arr = fit_weights(Z, y)
    pred = Z @ w_arr
    r2 = 1.0 - float(((y - pred) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())
    return dict(mu=mus, sigma=sigmas, w=dict(zip(component_keys, map(float, w_arr))),
                n_samples=n, r2=r2, fallback=False)
```

実装との違いは、実装が `mu_y` / `sigma_y` / `mse` も返して CSV に書くことと、`fit_weights` 相当の部分が `fit_one` の中にインライン展開されていることくらいです。

いくつか設計上の細部を補足します。

- **初期値は均等重み**(`1/k`)。制約を満たす点から始めると SLSQP が安定します。
- **勾配を渡す**(`jac=grad`)。渡さなくても数値微分で動きますが、渡すと反復回数と精度が安定します。行数 6,000 × 5 列の行列積なので計算は軽微です。
- **最後に `clip` と正規化**。SLSQP の解は制約を `ftol` の範囲で満たすだけなので、`−1e-12` のような値や `Σw = 0.9999999` が出ます。CSV に書く前に非負にして合計 1 に揃え、下流(`build_index.py`、fun-site)が「Σw = 1」を前提にできるようにしています。
- **`n < 60` はフォールバック**。均等重み `1/n_components` を返し、`fallback = True` を立てます。閾値 60 は「10 レース分」の目安です。

### 合成データで動作を確かめる

真の重みを `(0.45, 0.25, 0.10, 0.15, 0.05)` と決め、5 つの素点から潜在的な強さを作り、6 艇ずつのレースで潜在強さの順位を着順にした合成データ(12,000 艇行、`motor` の 30% を欠損)で `fit_one()` を走らせると、推定値は `(0.475, 0.270, 0.084, 0.142, 0.029)` になりました。着順という粗い観測を通しているので完全には戻りませんが、順序と大きさは回復しています。`motor` が真値より小さく出ているのは §5 で述べる「欠損を z=0 で補完する」ことの副作用です。

同じデータで `weather` を潜在強さと **逆相関** する列に差し替えると、推定値は `w_weather = 0.000` になります。制約なしの最小二乗なら負の係数が付くところを、非負制約が 0 で止めます。この「効かない成分は 0 に張り付く」挙動が、次節の説明可能性の土台です。

## 3. なぜこの形にしたか

### 強さpt が「寄与の和」に分解できる

`build_index.py` は学習済みの `(μ_k, σ_k, w_k)` を使って、1 艇ごとに次を計算します。

```
z_k     = (素点_k − μ_k) / σ_k
pt_k    = 50 + 10 × z_k              # 偏差値pt
寄与_k   = w_k × pt_k
強さpt   = Σ_k 寄与_k
```

`Σw = 1` があるので、

```
強さpt = Σ_k w_k (50 + 10 z_k) = 50 Σ_k w_k + 10 Σ_k w_k z_k = 50 + 10 Σ_k w_k z_k
```

となり、**強さpt はそれ自体が偏差値スケールの線形結合** です。index CSV には `N枠_枠番pt`(偏差値pt)、`N枠_寄与_枠番pt`(寄与)、`N枠_強さpt` が並んでいて、5 つの寄与列を足すと強さpt に一致します(小数第 2 位で丸めているので ±0.01 の差は出ます)。

`w ≥ 0` があるので、どの成分も「偏差値pt が高いほど強さpt が上がる」向きに固定されます。fun-site のレース詳細ページは、この寄与列をそのまま「この艇が強い理由の内訳」として表示しています(第 16 章)。もし負の重みを許すと、「展示pt が高いのに強さpt が下がる」成分が出て、内訳として読めなくなります。

![寄与への分解](/images/boatrace-ml-system/07-contribution-decomposition.png)
<!-- 図: 1 艇について、5 つの偏差値pt(枠番 67.5 / 選手 38.3 / モーター 41.6 / 展示 50 / 気象 50)に重み(0.36 / 0.22 / 0.12 / 0.21 / 0.08)を掛けて寄与(24.4 / 8.6 / 5.0 / 10.6 / 4.2)にし、積み上げ棒で強さpt 52.7 になる様子。数値は index CSV 2026-08-01 桐生 1R 1枠(daily 行)のもの -->

### Σw = 1 で偏差値スケールが「ほぼ」保たれる

上の式から、学習窓の中では強さpt の平均は厳密に 50 です(各 `z_k` の平均が 0 だから)。分散は成分間の相関 `ρ_kl` に依存します。

```
Var(強さpt) = 100 × Σ_k Σ_l w_k w_l ρ_kl
            ≤ 100 × (Σ_k w_k)² = 100          (|ρ_kl| ≤ 1、w ≥ 0 より)
```

つまり **標準偏差は 10 を超えません**。等号は全成分の相関が 1 のときだけで、成分が互いに独立なら `10 × √(Σ w_k²)` まで縮みます。福岡の 2026-08 の重みで計算すると `10 × √(Σ w_k²) = 5.54` です。

実際の値を公開 CSV で確かめると、2026 年 8 月の `v1_basic` の realtime 行(24 場、26,379 艇行)で強さpt の平均は 49.89、標準偏差は 5.91、場ごとの標準偏差は 5.22〜6.63 でした。福岡は平均 49.72、標準偏差 6.06(927 艇行)です。ドキュメントは「平均 50 ± 10 のスケールに収まる」と書いていますが、正確には「平均 50、標準偏差は 10 以下(実測 6 前後)」です。

標準偏差が 10 に届かない理由はもう 1 つあります。8 月の偏差値pt は 2〜7 月の `(μ, σ)` で標準化されているので、8 月の分布は平均 50・標準偏差 10 からずれます。たとえば福岡の 8 月の選手pt は平均 48.6、標準偏差 6.8 でした(欠損補完値 30 が平均を下げる効果も含みます。第 4 章)。

このずれは買い目に効きます。第 8 章の買い目生成は 1 マーク走行距離(予測 ST + 強さpt / 50)の許容窓で候補を選ぶので、強さpt の散らばりが 10 ではなく 6 なら、同じ窓幅でも候補に入る艇の数が変わります。スケールの前提を置くときは、`Σw = 1` だけでなく相関の効果まで見ておく必要があります。

### 勾配ブースティングではなく線形モデルにした理由

着順予測の精度だけなら、勾配ブースティングのような非線形モデルの方が高くなる可能性は十分にあります。それでも線形モデルを選んだのは、資料に明示的な比較実験の記録はありませんが、設計上の判断として次の 3 点が優先されたためです。

1. **寄与への分解が厳密に成り立つ**。非線形モデルでは SHAP 値などの事後的な近似説明が要りますが、線形モデルなら `寄与_k = w_k × pt_k` がそのまま説明です。
2. **下流が同じ数値を再現できる**。fun-site(TypeScript)は weights CSV の `mu_k / sigma_k / w_k` の 3 列だけを読んで、素点 → z → 偏差値pt → 寄与を小数第 2 位まで再現しています(第 16 章)。学習済みモデルのバイナリを 2 言語で共有する必要がありません。
3. **月次で 24 場 × 予想者数ぶんを学習して CSV で配れる**。重みファイルは場 1 行、成分あたり 3 列で、git で差分が読めます。

回収率で見た予想者の優劣は、この線形モデルの上で成分を差し替えて A/B 比較しています(第 10 章)。モデルの形を変えるのは「成分の差し替えで改善が止まったら」という順序です。

### R² の読み方

`r2` は標準化した `y` に対する決定係数です。2026-08 の `v1_basic` は 24 場で 0.168(戸田)〜0.369(徳山)、平均 0.275 でした。着順という 6 値の観測に対して、締切前に分かる 5 つの数字で 2〜4 割の分散を説明している、という読み方になります。

ただしこの R² は学習窓での in-sample の値で、モデル選択には使っていません。予想者の採否は回収率のペア比較で決めます(第 9 章)。`r2` と `mse` を CSV に残しているのは、月ごとの推移で「学習が壊れていないか」を見るためです。

## 4. 場ごとの重みを読む

### なぜ場ごとに学習するか

ボートレース場は 24 か所あり、水面の広さ、水の質(海水・淡水・汽水)、風の通り方、イン(1 コース)の勝ちやすさが違います(第 1 章)。全場で 1 組の重みを学習すると、これらの違いは「誤差」として平均されてしまいます。場ごとに 5 個の重みを学習しても、1 場あたり 4,500〜7,000 行あるので過学習の心配はありません。

### 対照的な 2 場

`weights/v1_basic/2026-08.csv`(学習窓 2026-02-01〜2026-07-31)から、重みの構成が対照的な戸田と福岡を抜き出します。参考に江戸川も並べます。

| 列 | 戸田 | 福岡 | 江戸川 | 24 場の範囲 |
| --- | --- | --- | --- | --- |
| `n_samples` | 5,273 | 4,521 | 4,820 | 4,521〜7,094 |
| `w_waku`(枠番) | **0.281** | 0.449 | **0.480** | 0.281〜0.480 |
| `w_racer`(選手) | 0.267 | 0.205 | 0.242 | 0.176〜0.304 |
| `w_motor`(モーター) | **0.128** | 0.073 | 0.107 | 0.070〜0.128 |
| `w_exhibit`(展示) | 0.230 | 0.237 | **0.055** | 0.055〜0.255 |
| `w_weather`(気象) | 0.095 | **0.036** | **0.117** | 0.036〜0.117 |
| `r2` | **0.168** | 0.356 | 0.218 | 0.168〜0.369 |

太字はその列の 24 場中の最小値または最大値です。

- **福岡** は枠番の重みが 0.449 と大きく、気象の重みが 0.036 と最小です。強さpt のほぼ半分が「どのコースか」で決まります。ドキュメント(`docs/data/estimate.md`)も福岡を「枠番pt の重みが大きい(イン強度が高い)」場の例に挙げています。
- **戸田** は枠番の重みが 0.281 と 24 場で最小で、選手 0.267 とほぼ同じ比重です。モーターの重みは 0.128 と最大です。R² も 0.168 と最小で、5 成分で説明できる割合が最も小さい場です。
- **江戸川** は枠番 0.480 と気象 0.117 が最大で、展示 0.055 が最小です。展示の重みが極端に小さいのは、他の場より展示の情報が着順に結びつきにくいためと考えられますが、資料には理由の分析はありません。

同じドキュメントは桐生を「気象pt の重みが大きい(波が立ちやすい)」場の例にしていますが、2026-08 の桐生の `w_weather` は 0.083 で、24 場の平均 0.076 とほぼ同じです。場の性格の読みは、必ず当月の CSV で確かめてください。

![24 場の重み](/images/boatrace-ml-system/07-weights-by-stadium.png)
<!-- 図: 横軸に 24 場(場コード順)、各場について w_waku / w_racer / w_motor / w_exhibit / w_weather を積み上げ棒(合計 1)で描く。データは weights/v1_basic/2026-08.csv。戸田・福岡・江戸川をハイライト -->

24 場の平均は枠番 0.402、選手 0.226、展示 0.202、モーター 0.093、気象 0.076 です。どの場でも枠番が最大で、モーターと気象は合わせても 0.11(福岡)〜0.22(江戸川)にとどまります。第 5 章で手間をかけたモーター能力指数の重みがこの程度である事実は、成分の改善が回収率に結びつきにくかったこと(第 10 章の `v4_motor` の結果)と整合しています。

### 月をまたいだ安定性

2026-08 と 2026-09 の重みファイル(学習窓が 1 か月ずれる)を比べると、成分ごとの `|Δw|` の 24 場平均は 0.004(モーター)〜0.011(枠番・選手)でした。窓が 6 か月あるので、1 か月ずれても重みは大きくは動きません。逆に言えば、季節性(第 4 章の枠番pt の季節テーブル)は素点側で吸収させ、重みには急な変化を求めない設計です。

### 出力列

重みファイルは場 1 行で、次の列を持ちます。

| 列 | 意味 |
| --- | --- |
| `stadium` | 場名(全角) |
| `n_samples` | SLSQP に使った行数 |
| `mu_{k}` / `sigma_{k}` | 成分 k の素点の平均・標準偏差(偏差値変換に使う) |
| `w_{k}` | 成分 k の重み(非負、合計 1) |
| `mu_y` / `sigma_y` | `7 − 着順` の平均・標準偏差 |
| `mse` / `r2` | 標準化スケールでの平均二乗誤差と決定係数 |
| `fallback` | 1 = サンプル不足(n < 60)で均等重みに倒した |

`fallback` 列を残しているのは、均等重みの場を「学習した結果たまたま 0.2 ずつになった」と取り違えないためです。2026-08 の `v1_basic` はどの場も `fallback = 0` で、最小の `n_samples` は 4,521(福岡)でした。フォールバックが実際に効くのは、新しい成分を投入した初月や、データ収集が止まっていた期間の後です。

## 5. 短期成分の扱い

### モーターは 6 か月さかのぼれない

モーターpt の素点(第 5 章)は `data/programs/motor_stats/` を起点に履歴を組みますが、この CSV は **その日に開催がある場しか収録しません**。さらにモーター期(モーターの交換周期)の起算日より前のデータは使えないので、学習窓の前半ではモーターの素点が NaN になる行が大量に出ます。実装のコメントはこれを「長期 backfill が原理的にできない」と表現しています。

素朴に「5 成分が全部揃った行だけで学習する」と、モーターの都合で **他の 4 成分の学習窓まで削られて** しまいます。そこで `build_weights.py` は短期成分を `SHORT_HISTORY_COMPONENTS = {"motor", "motor4"}` として宣言し、`fit_one()` の中で 2 段階に扱いを分けています。

1. **`(μ_k, σ_k)` は成分ごとに、その列が欠損していない行だけで計算する**。モーターの `μ, σ` は値がある行から、枠番の `μ, σ` は枠番の値がある行から求めます。これにより、モーターの偏差値変換のスケールは短い履歴なりに正しく保たれます。
2. **SLSQP の行は長期成分と着順が揃っていれば採用し、短期成分の欠損は `μ_k` で補完する**。補完値は標準化後に `z = 0` になるので、その行はモーターについて「平均並み」として扱われ、他の 4 成分の学習には普通に貢献します。

### 補完の副作用

`z = 0` で補完した行は、モーターの重みを推定する上では情報を持ちません。むしろ「モーターが平均なのに着順は良い(悪い)」という見かけの無関係を増やすので、`w_motor` は真の値より **小さめ** に推定されます。§2 の合成データで `motor` を 30% 欠損させたとき、真値 0.10 に対して推定が 0.084 になったのがこの効果です。

この偏りは、行を落として他成分の学習窓を削るコストと比べて受け入れています。モーターの重みは元々 0.07〜0.13 と小さく、偏りが買い目に与える影響も小さいためです。新しい短期成分を追加するときは、この frozenset に追記するだけで同じ扱いになります(`v4_motor` の `motor4` がそうでした)。

## 6. 運用

### 月次バッチ

重み学習は Cloud Run Jobs の `monthly-weights` として動きます(第 11 章)。Cloud Scheduler が **毎月 1 日 06:00 JST** に起動し、`infra/run-monthly-weights.sh` が次を行います。

1. 対象月 + 過去 6 か月 + 1 か月(`motor_stats` の 7 日フォールバック用)= 8 か月ぶんのデータを sparse-checkout する
2. `python scripts/build_weights.py --month YYYY-MM --all-active` で active な全予想者の重みを学習する(同じジョブでスジ表や決まり手モデルなどの月次テーブルも再生成します。第 20〜21 章)
3. `data/estimate/stadium/weights/{predictor_id}/YYYY-MM.csv` を commit して push する

06:00 という時刻には理由があります。日次バッチ `daily-sync` は 07:30 JST に走るので、その前に重みを更新しておけば、**月初の日の daily 行と realtime 行が同じ重みで計算されます**。結果 CSV は各レースの締切後 3〜30 分で追記されるので、1 日の 06:00 には前月末日の結果まで揃っています。学習窓の最後の日を取りこぼさない、ぎりぎりの時刻です。

`--all-active` はレジストリ(第 10 章)の `active_predictors()` をループします。予想者を追加・退役させても、このジョブの設定は変わりません。

```bash
# 手動で特定月・特定予想者だけ学習する(ローカル、全履歴 checkout が前提)
python scripts/build_weights.py --month 2026-08 --predictor v1_basic

# active な全予想者(本番ジョブと同じ)
python scripts/build_weights.py --month 2026-08 --all-active
```

### 重みファイルの解決規則

`build_index.py` は index を計算する日 `day` に対して、**`day` の月以下で最新の `YYYY-MM.csv`** を使います。規則は `PredictorSpec.resolve_weights_csv_path()` に 1 か所だけ書かれています。

```python:registry.py(抜粋)
def resolve_weights_csv_path(self, repo: Path, day: dt.date) -> Path | None:
    weights_dir = self.weights_dir(repo)
    if not weights_dir.exists():
        return None
    target_tag = f"{day:%Y-%m}"
    candidates = [
        p for p in sorted(weights_dir.glob("????-??.csv"))
        if p.stem <= target_tag
    ]
    return candidates[-1] if candidates else None
```

ファイル名が `YYYY-MM` なので文字列比較で月の大小が決まり、`sorted` して `stem <= target_tag` の最後を取るだけです。この規則によって、

- 当月の重みがまだ無い(月次ジョブが失敗した、新しい予想者の初月)場合は、直近の過去月に自動でフォールバックする
- 未来月の重みを先に置いておく運用もできる
- ディレクトリ自体が無い、または 1 つも無い場合は `None` を返し、`build_index.py` は強さpt を NaN で出力する

同じ関数を GCS ミラー(第 11 章)も使い、fun-site には「その日の index CSV を作ったのと同じ重みファイル」が配られます。解決規則を 2 か所に書くと、index と fun-site の検算(第 16 章)が食い違う原因になるので、1 か所に集約しています。

### 新しい予想者の初月をブートストラップする

新しい予想者を投入する月には、その予想者の重みファイルがまだありません。ケースは 2 つに分かれます。

**成分が既存の予想者と同じ場合**は、既存のファイルをコピーします。`fit_one()` の入力は成分の素点列と着順だけなので、成分が同じなら学習結果も同じになるからです。買い目の作り方だけを変えた `v9_suji` と `v10_kimarite` は `v1_basic` の重みをコピーして始めました。実際に `weights/v10_kimarite/2026-08.csv` と `2026-09.csv` は `v1_basic` のものとバイト単位で同一です(翌月以降は `--all-active` が自動で同じ内容を生成します)。

**成分の組み合わせが新しい場合**は、コピー元がありません。`v7_aggregate`(`course` + `motor4`)がそうで、設計書(`docs/design/aggregate_v7.md` §3)は全履歴を checkout したローカルで学習してから commit する手順を定めています。

```bash
python scripts/build_weights.py --predictor v7_aggregate --month 2026-07
```

本番ジョブは sparse-checkout で 8 か月ぶんしか持たないので、投入月を過去にさかのぼって学習し直す用途には向きません。初月だけローカルで作り、翌月から自動化に乗せる、という分担です。

## 元資料

- [scripts/build_weights.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_weights.py) — 学習テーブルの構築、`fit_one()`、`SHORT_HISTORY_COMPONENTS`、出力列
- [scripts/build_index.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_index.py) — 重みの適用と寄与の計算(`_build_one_race_row`)、`find_weights_file`
- [scripts/boatrace/predictors/registry.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py) — `resolve_weights_csv_path()`、ブートストラップに関するコメント
- [docs/data/estimate.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) — Strength Index、生成パイプライン、Stadium Parameters(重みファイルの列定義)
- [docs/design/aggregate_v7.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/aggregate_v7.md) — §3 重みのブートストラップ
- [docs/infrastructure.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md)、[infra/run-monthly-weights.sh](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-monthly-weights.sh) — monthly-weights ジョブのスケジュールと sparse-checkout
- [data/estimate/stadium/weights/v1_basic/2026-08.csv](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/data/estimate/stadium/weights/v1_basic/2026-08.csv) — 本文の表の出典

## 演習

公開 CSV だけを使って、1 場・1 か月ぶんの重みを推定し、実際の重みファイルと比べます。

1. 2026 年 8 月の `v1_basic` の index CSV(`https://boatracecsv.github.io/data/estimate/v1_basic/2026/08/DD.csv`、DD = 01〜31)と結果 CSV(`https://boatracecsv.github.io/data/results/realtime/2026/08/DD.csv`)を取得します。
2. index CSV は `状態 = realtime` の行だけを使います(daily 行は展示pt・気象pt が 50 固定です)。6 枠ぶんの `N枠_枠番pt` … `N枠_気象pt` を 1 艇 1 行に縦持ちにし、`z = (pt − 50) / 10` で標準化スコアに戻します。
3. 結果 CSV の `1着_艇番` … `6着_艇番` から `(レースコード, 枠番, 着順)` を作り、`(レースコード, 枠番)` で inner join します。
4. 福岡(レース場コード `22`)の行を §2 の `fit_one()` に渡し、`weights/v1_basic/2026-08.csv` と `2026-09.csv` の福岡の行と比べます。

参考として、筆者が実行した結果は次のとおりです(福岡、927 艇行)。

| 成分 | 演習の推定(8 月のみ) | `2026-08.csv`(2〜7 月) | `2026-09.csv`(3〜8 月) |
| --- | --- | --- | --- |
| 枠番 | 0.489 | 0.449 | 0.456 |
| 選手 | 0.215 | 0.205 | 0.203 |
| モーター | 0.061 | 0.073 | 0.066 |
| 展示 | 0.201 | 0.237 | 0.237 |
| 気象 | 0.034 | 0.036 | 0.038 |

1 か月ぶんの推定でも重みの順序と大きさは一致します。24 場すべてで同じことをすると、成分ごとの `|推定 − 2026-08.csv|` の平均は 0.02〜0.05 でした。差の主な原因は、(a) 学習窓が 1 か月と 6 か月で違う、(b) 演習では偏差値pt を 8 月のデータで再標準化している、(c) index CSV では欠損が 50(選手pt は 30)で補完済みで NaN に戻せない、の 3 点です。

発展として次を試してください。

- `fit_weights()` の `bounds` と `constraints` を外して通常の最小二乗にし、どの成分に負の係数が付くか、寄与の内訳として読めるかを確かめる。
- 目的変数を `7 − 着順` から「1 着なら 1、それ以外は 0」に変えて重みを比べる。1 着だけを当てたいなら、どの成分の重みが増えるかを見る。
- 24 場の強さpt の標準偏差(realtime 行)を計算し、§3 の `10 × √(wᵀRw)` と比べる。
