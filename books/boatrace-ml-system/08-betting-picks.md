---
title: "買い目の作り方: 強さポイントから 3 連単フォーメーションへ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 点推定(強さpt)を「買う集合」に変換する。許容窓、点数、選定基準が回収率を直接動かす |
| システム | 買い目生成をどこに置くか(fun-site 側)、画面と集計が同じ関数を通る設計、予想者ごとのフラグ |

## 1. フォーメーションという表現

- 各着の候補窓の直積で買い目を作る。1 着候補 × 2 着候補 × 3 着候補
- 候補の選び方(強さpt の順位と差)と、平均点数(control は 11.5 点)

## 2. 実装は fun-site 側にある

- boatracecsv は強さpt(index CSV)までを出し、買い目は fun-site の `prediction-builder.ts` が組む
- 例外: 穴予想(v9 / v10)はフォーメーションで表現できないため boatracecsv 側で確定して CSV で配る(第 21 章)

## 3. 画面と集計を食い違わせない

- `bettingToleranceFor()` / `bettingBasisFor()` / `bettingStyleFor()` をバッチと web の両方が必ず通す
- 片側が渡し忘れると「画面の買い目」と「回収率の母数の買い目」がずれる

## 4. 選定基準を変えるとどうなるか(v8_aionly)

- v7 と同一レシピで、買い目候補の選定だけ「強さpt ±5.0pt 窓」に変えた
- 結果: control 比 −10.62pt、p=0.0001、日次 13/13 日で control 未満。買い目の作り方はモデルと同じくらい効く

## 5. 簡略版コード(TypeScript)

強さpt の配列からフォーメーションを生成し、点数を返す関数を 50 行で示す。

## 元資料

- fun-site `packages/batch/src/site-builder/prediction-builder.ts`、`packages/shared/src/predictors.ts`、`docs/domain.md` §1・§4
- boatracecsv `docs/data/estimate.md`(v8_aionly の退役ノート)

## 演習

許容窓を ±3 / ±5 / ±8pt に変えて、1 か月分の平均点数と的中率がどう動くか計算する。

## 執筆メモ

- v8 の詳細な検定結果は第 10 章に譲り、ここでは「選定基準が効く」ことだけ示す。
