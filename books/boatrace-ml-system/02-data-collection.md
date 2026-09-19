---
title: "公式データの収集: 1 レース 1 行の CSV"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 欠損の意味を決める(`0.00` は実績なし)、学習に使う 3 段階のデータ(事前 / 直前 / 結果)と時間順序 |
| システム | スクレイパーの層構造、レートリミットと指数バックオフ、冪等な CSV 追記、共通キーによる JOIN |

## 1. データソース

- 公式サイト(`www1.mbrace.or.jp`)の日次ファイルと、`race.boatcast.jp` の準リアルタイム JSON
- 取得できる情報を「事前 / 直前 / 結果」の 3 段階に整理した表

## 2. 1 レース 1 行という設計

- 12 桁レースコード `YYYYMMDDjjrr` を全ファイル共通の主キーにする
- 6 艇分を横に展開した wide 形式にした理由: `pd.read_csv` と `merge(on="レースコード")` だけで特徴量テーブルが組める
- パス規約 `data/{カテゴリ}/{種別}/YYYY/MM/DD.csv` と HTTPS 配信

```python:join_example.py
import pandas as pd
BASE = "https://boatracecsv.github.io/data"
day = "2026/08/01"
cards = pd.read_csv(f"{BASE}/programs/race_cards/{day}.csv", dtype=str)
results = pd.read_csv(f"{BASE}/results/realtime/{day}.csv", dtype=str)
df = cards.merge(results, on="レースコード")
```

## 3. スクレイパーの層構造

downloader → extractor → parser → converter → storage → git_operations という分割と、各層の責務。

## 4. 礼儀正しく取得する

- `RateLimiter`(既定 3 秒間隔)と `ExponentialBackoff`。404 / 403 は再試行せず即スキップ、5xx のみリトライ
- 簡略版コード(50 行程度)

## 5. 冪等な追記

- 同一レースコードは 1 日 1 行。再実行が常に安全になるまで dedup を徹底する
- 追記行が 0 なら commit しない

## 6. 欠損の意味を決める

- `Nコース_F` はドキュメントの 1/0 ではなく文字 `"F"` / 空欄だった、という実態の発見
- 全国平均 ST `0.00` は「実績なし」。意味を決めずに数値として流すと下流で最速扱いになる

## 元資料

- boatracecsv `docs/data/README.md`、`docs/data/programs.md`、`docs/data/results.md`、`docs/development.md`
- `scripts/boatrace/downloader.py`、`parser.py`、`converter.py`、`storage.py`

## 演習

任意の 1 週間分の race_cards と results を JOIN し、級別(A1/A2/B1/B2)ごとの 1 着率を出す。

## 執筆メモ

- 公式サイトの利用規約と取得間隔について一段落入れる。
- ここでは「取れるもの」を示すだけにし、各ファイルのスキーマ詳細は付録に回す。
