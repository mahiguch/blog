---
title: "説明可能性: 寄与の分解と検算ページ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 線形モデルの寄与分解を UI まで貫く。再現できない成分は「再現できる材料」を上流に出させる |
| システム | 検算ページの設計、Python 実装を TypeScript に移植するときの罠、移植の検証粒度 |

## 1. 寄与の積み上げ棒

- 枠番・選手・モーター・展示・気象の寄与pt を枠ごとに横棒で可視化
- 凡例の各項目が、その成分の検算ページへのリンクになっている

## 2. 5 つの検算ページ

- `/lanes/` `/racers/` `/exhibition/` `/weather/` `/motors/` が、成分ごとに「素点 → 偏差値pt → 寄与」を実値で展開する
- 再現値が index CSV と一致したときだけ「(表示値と一致)」を出す

## 3. 再現できない成分をどうするか

- モーターpt だけは全 24 場横断のベースラインに依存し、fun-site 側で原理的に計算できない
- 上流に `estimate/motor_pt/{runs,motors,baseline}` として計算過程そのものを配ってもらう形にした
- トレードオフ: JSON は 74KB → 183KB(2026-08-23)

## 4. Python → TypeScript 移植の罠

| 罠 | 症状 |
| --- | --- |
| Python `round()` は偶数丸め | `Math.round` だと 56.5 で 1pt ずれる |
| 生値を `toFixed(4)` で丸める | 丸めないと気象pt が 0.01 ずれる。`x * 1e4` を挟むと二進誤差で境界がずれる |
| 全国 5 節と当地 5 節の重複 | 重複排除しないと当地の節が 2 回計上される |
| 優勝戦の `[F]` | 括弧に着順以外が入ると得点にも出走回数にも計上されない |
| 欠損補完 | 選手pt だけ 50 ではなく 30 |

- 検証: 2026-08 の 7,996 エントリで照合し、不一致は 4 桁丸め境界の 1 件のみ
- 簡略版コード(TypeScript、偶数丸めと選手pt の再現、60 行)

## 5. 何を出さないか

枠番詳細ページに選手個人の過去 10 走を出さない理由: 「個人の成績は入っていない」という説明の直下に個人成績を並べると混同する。

## 元資料

- fun-site `docs/domain.md` §1(成分ごとの再現可否)、`docs/architecture.md`(2026-08-23)、`docs/web.md`、`components/AiEvaluationChart.astro`、`packages/web/src/pages/{lanes,racers,exhibition,weather,motors}/`
- boatracecsv `docs/data/motor_pt.md`、`docs/data/estimate.md`(展示pt の算出手順)

## 演習

Python の `round()` と JavaScript の `Math.round` で結果が異なる入力を 5 つ見つけ、TypeScript で偶数丸めを実装する。

## 執筆メモ

- 「再現できないなら、再現できるだけの材料を上流に出させる」という交渉が設計になっている、を章の主題にする。
