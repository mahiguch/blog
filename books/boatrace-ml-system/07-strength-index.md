---
title: "強さポイント: 非負制約付き最小二乗"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 線形モデル、制約付き最適化(SLSQP)、Σw=1 と w≥0 が「寄与への分解」を可能にする、場ごとに学習する意味、R² の読み方 |
| システム | 月次バッチ、weights の解決規則(対象月以下で最新)、サンプル不足時のフォールバック、ブートストラップ |

## 1. 目的変数と学習データ

- 直近 6 か月の全レースについて特徴量を計算し、結果と `(レースコード, 枠番)` で inner join
- 目的変数は `7 − 着順` を標準化したもの

## 2. 制約付き最小二乗

```
minimize  ‖Z·w − y‖²
subject to  w ≥ 0,  Σw = 1
```

- 場ごとに解く。SLSQP で数十行
- 簡略版コード(`fit_one` の骨格、60 行程度)

```python:fit_weights.py
import numpy as np
from scipy.optimize import minimize

def fit_weights(Z: np.ndarray, y: np.ndarray) -> np.ndarray:
    k = Z.shape[1]
    obj = lambda w: float(((Z @ w - y) ** 2).sum())
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    res = minimize(obj, np.full(k, 1.0 / k), method="SLSQP",
                   bounds=[(0.0, 1.0)] * k, constraints=cons)
    return res.x
```

## 3. なぜこの形にしたか

- `強さpt = Σ (w_k × 偏差値pt_k)` なので、`寄与_k = w_k × 偏差値pt_k` と分解して「なぜこの艇が強いか」を説明できる
- Σw=1 により強さpt も平均 50・SD 10 に収まる
- 勾配ブースティングより精度が低い可能性は承知の上で、説明可能性を優先した判断

## 4. 場ごとの重みを読む

- 重みを 24 場で並べると場の性格が数値で見える(気象の重みが大きい場、枠番の重みが大きい場)
- `n_samples` / `mse` / `r2` / `fallback` を出力に残す。n < 60 の場は均等重み

## 5. 短期成分の扱い

motor は motor_stats が開催場しか収録せず長期 backfill ができないため、`SHORT_HISTORY_COMPONENTS` として z=0 で補完する。

## 6. 運用

- 毎月 1 日 06:00 JST に monthly-weights が生成し、`build_index.py` は「対象月以下で最新」の weights を選ぶ
- 新しい予想者の初月は、成分が同じ既存予想者の weights をコピーしてブートストラップする

## 元資料

- `scripts/build_weights.py`、`docs/data/estimate.md`(Strength Index、生成パイプライン)、`docs/design/aggregate_v7.md`(weights のブートストラップ)

## 演習

公開 CSV から 1 場・1 か月分の (偏差値pt, 着順) を組み、上のコードで重みを推定して `weights/v1_basic/YYYY-MM.csv` と比べる。

## 執筆メモ

- 「SD 10 スケールが崩れない」ことを式で 2 行示す。
- 2026-08 時点の weights CSV から、対照的な 2 場の重みを表にして載せる。
