---
title: "Astro で作る予想ページ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 予想者ごとに表示と買い目の挙動を宣言する。モデル側の変更を UI に波及させない |
| システム | pnpm monorepo(shared / batch / web)、ゼロ JS の SSG、spec 駆動描画、艇色を基底にした色設計 |

## 1. パッケージ構成

- `shared`: 型、定数(24 場、艇色)、予想者レジストリ(TypeScript 版)
- `batch`: CSV 取得と RacePrediction の生成、集計、ビルドとデプロイ
- `web`: Astro のページとコンポーネント

## 2. TypeScript 側の PredictorSpec

- id / displayName / slot / status / startedAt / componentKeys に加えて、挙動フラグ `useEstimatedST` / `strengthOnlyBetting` / `bettingStyle` / `showsAiPanels`
- boatracecsv の registry と ID を同期する。片方だけ足すと fetcher が CSV を取りに行かない
- 簡略版コード(TypeScript、50 行)

## 3. spec 駆動描画

- v7_aggregate 投入時にレース詳細ページのカード描画を slot / ID のハードコード列挙から `predictorById()` 経由に一般化
- 副作用で、分岐に未追加だった v6_course の図が初めて表示された

## 4. ページ構成

- 日付 → 場 → レース詳細、予想者別の成績、検算ページ(第 16 章)、統計(第 17 章)
- 静的ページはゼロ JS。SVG も Astro がビルド時に生成する

## 5. 色とレイアウト

- 艇色(1 白 / 2 黒 / 3 赤 / 4 青 / 5 黄 / 6 緑)を全 UI の基底にする
- iPhone 幅 375px に対して min-content 285px < 311px、という実測ベースの列設計
- sticky 列の影のために `border-collapse` ではなく `border-separate` を使う理由

## 元資料

- fun-site `docs/web.md`、`docs/development.md`、`packages/shared/src/predictors.ts`、`packages/shared/src/constants/`、`docs/architecture.md`(2026-07-23 の経緯)

## 演習

`predictors.ts` に表示専用の予想者を 1 つ追加し、レース詳細ページにカードが増えることを開発サーバーで確認する。

## 執筆メモ

- Astro の基礎は前提とするので、コンポーネント構文の説明は不要。ページとデータの対応表を中心に。
