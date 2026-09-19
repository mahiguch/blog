---
title: "特徴量パイプラインの高速化: FeatureContext"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 月次学習(6 か月 × 全レース)で特徴量を再計算するコスト |
| システム | 「素朴に正しい実装」を計測して直す、セッションインデックスの事前計算、メモ化、ロールアウト計画 |

## 1. 観測: 月次重み学習が 75 分かかる

- race_cards の open が約 41 万回。日ごとに 6 節分の履歴を舐め直していた
- 根本原因は「関数が毎回ゼロから履歴を組む」構造

## 2. 設計: FeatureContext

- 公開 API を変えず、内部に「セッションインデックス」を事前計算して持つ
- race_cards / title のメモリキャッシュ、`period_starts` の日次メモ化、`motor_history(day)` の再構成
- open 回数 41 万 → 270、75 分 → 10〜15 分

## 3. 検証とロールアウト

- 既存ユニットテストに加え、旧実装との出力一致テスト(parity)
- PR1(コンテキスト導入、未配線)→ PR2(build_weights を配線)の 2 段階
- 検討して却下した代替案

## 4. 簡略版コード

セッションインデックスを dict で持ち、`motor_history(day)` を O(1) で返す最小構成を 60 行で示す。

## 元資料

- `docs/design/feature_context_refactor.md`、`scripts/boatrace/index_features.py`(FeatureContext)、`scripts/build_weights.py`

## 演習

自分の特徴量関数に対して、ファイル open 回数を数えるデコレータを書き、ボトルネックを見つける。

## 執筆メモ

- 短い章でよい。「ML の前に計測」という教訓の章。
