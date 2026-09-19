---
title: "付録: CSV スキーマ早見表と参照リンク"
---

## 1. データファイル一覧

| カテゴリ | ファイル | パス |
| --- | --- | --- |
| 事前 | Race Title | `data/programs/title/YYYY/MM/DD.csv` |
| 事前 | Race Cards | `data/programs/race_cards/YYYY/MM/DD.csv` |
| 事前 | Waku10 | `data/programs/waku10/YYYY/MM/DD.csv` |
| 事前 | Monthly Schedule | `data/programs/monthly_schedule/YYYY/MM.csv` |
| 事前 | Recent National / Local | `data/programs/recent_{national,local}/YYYY/MM/DD.csv` |
| 事前 | Motor Stats / History | `data/programs/motor_{stats,history}/YYYY/MM/DD.csv` |
| 直前 | Preview 4 ソース | `data/previews/{tkz,stt,sui,original_exhibition}/YYYY/MM/DD.csv` |
| 直前 | 得点率早見 | `data/previews/tokuten_hayami/YYYY/MM/DD.csv` |
| 直前 | Odds 3 ソース | `data/previews/{od1,od2,od3}/YYYY/MM/DD.csv` |
| 結果 | Realtime Results / Payouts | `data/results/{realtime,payouts}/YYYY/MM/DD.csv` |
| 派生 | Strength Index | `data/estimate/{predictor_id}/YYYY/MM/DD.csv` |
| 派生 | Racer ST | `data/estimate/racer_st/YYYY/MM/DD.csv` |
| 派生 | Motor pt 内訳 | `data/estimate/motor_pt/...` |
| 派生 | 荒れ度・穴予想 | `data/estimate/kimarite/...` |
| 派生 | 場別パラメータ | `data/estimate/stadium/{win_rate,sui_params,course_win_rate}.csv`、`weights/{predictor_id}/YYYY-MM.csv` |

ルートはすべて `https://boatracecsv.github.io/`。共通キーは 12 桁レースコード `YYYYMMDDjjrr`。

## 2. 用語集

枠番 / コース / ST / F(フライング)/ 決まり手 / スリット / 節 / 級別 / モーター期 / 偏差値pt / 寄与 / 強さpt / daily / realtime

## 3. 参照リンク

- boatracecsv: https://github.com/BoatraceCSV/boatracecsv.github.io(`docs/data/README.md` にスキーマ詳細)
- fun-site: https://github.com/BoatraceCSV/fun-site
- 公開サイト: https://boatrace-fun.net

## 執筆メモ

- スキーマの列定義は docs/data/*.md へのリンクで済ませ、ここでは一覧だけにする。
