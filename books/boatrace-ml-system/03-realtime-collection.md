---
title: "直前情報とリアルタイム収集"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 「締切前に取れる情報」の境界。展示タイム、進入コース、気象は締切 5 分前にしか揃わない |
| システム | 2 分毎に走るジョブの設計、締切窓の判定、キャッチアップモード、per-source 分割、独立 append |

## 1. 直前情報とは何か

- 4 ソース: tkz(展示タイム・体重・チルト)、stt(進入コース・スタート展示 ST)、sui(気象)、original_exhibition
- ソースごとに CSV を分ける理由: 同一レースの値の時間変化(特に気象)を保持でき、下流がそのまま読める

## 2. 締切窓の判定

- 開催一覧 JSON から締切時刻を得て、`[now+1分, now+10分]` に入るレースだけを対象にする
- 1 実行で 4 パス(preview / odds / result / payout)を回し、1 コミットにまとめる

## 3. 結果の取りこぼしとキャッチアップモード

- 動機: 2026-07-28 びわこ 7R 以降が SG 進行遅延で取れなかった
- 固定窓をやめ、未記録レースを終日再試行し、締切の古い順に 15 件ずつ処理して 300 秒タイムアウトを避ける

## 4. 結果と払戻を独立に append する

片方だけ取れたサイクルは次サイクルで補完される。「揃うまで待つ」より単純で壊れにくい。

## 5. 簡略版コード

締切窓の判定と、レースコード dedup で upsert する関数を 60 行程度で示す。

## 元資料

- `scripts/preview-realtime.py`、`scripts/boatrace/preview_csv.py`、`result_realtime.py`、`payout_realtime.py`
- `docs/data/previews.md`、`docs/data/results.md`、`docs/development.md`(Run Realtime Preview Scraper)

## 演習

`previews/stt` と `results/realtime` を JOIN し、スタート展示 ST と本番 ST の相関係数を計算する(答えは第 18 章: 0.047)。

## 執筆メモ

- ここで daily / realtime の「状態」列を導入し、第 4 章の DAILY_NEUTRAL_COMPONENTS につなぐ。
