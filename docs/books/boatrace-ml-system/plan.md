# 執筆計画: ボートレース予想AIを作って運用する

Zenn book `books/boatrace-ml-system/` の執筆計画。章の骨格は各章ファイルに書いてあり、
このファイルは全章に共通する方針と、章 → 元資料 → 掲載コードの対応表を持つ。

## 決定事項(2026-09-19)

| 項目 | 決定 |
| --- | --- |
| 構成 | 案A(縦断型)。開発の実際の順序に沿って、データ収集 → 特徴量 → モデル → 評価 → 運用 → 配信 → 発展 |
| 対象読者 | エンジニア。Python に加えて TypeScript / Astro の基礎知識を前提 |
| コード | 各章で「本質だけ 50〜100 行」に切り出した簡略版を掲載。実装は GitHub リンクで示す |
| 配信レイヤー | fun-site(TypeScript / Astro)も他の層と同じ粒度で解説する |
| インフラ | GCP(Cloud Run Jobs / Scheduler / Pub/Sub / Eventarc / Workflows / GCS / Cloud CDN)で解説 |
| 数値 | 回収率・p 値などは **2026 年 8 月時点**の値を使い、本文にそう明記する |
| 分量 | 上限なし。24 章 |

## 元リポジトリ

| 略称 | リポジトリ | 役割 |
| --- | --- | --- |
| boatracecsv | https://github.com/BoatraceCSV/boatracecsv.github.io | 収集・特徴量・モデル・CSV 配信(Python) |
| fun-site | https://github.com/BoatraceCSV/fun-site | 予想ページの生成と配信(TypeScript / Astro) |

リンクは `blob/main/<path>` 形式。ローカルの `/Users/mahiguch/dev/{boatracecsv.github.io,fun-site}` を参照して書く。
fun-site の README は License が Private なので、**公開範囲を執筆前に確認する**(非公開ならコードは書籍内で完結させる)。

## 章ごとの対応表

| 章 | ファイル | 主な元資料 | 掲載コード(簡略版) |
| --- | --- | --- | --- |
| 0 はじめに | 00-introduction | fun-site docs/architecture.md、boatracecsv README | なし(全体図) |
| 1 ドメイン | 01-boatrace-domain | fun-site docs/domain.md | なし |
| 2 データ収集 | 02-data-collection | boatracecsv docs/data/*.md、docs/development.md、scripts/boatrace/{downloader,parser,converter}.py | RateLimiter + backoff、レースコード JOIN |
| 3 リアルタイム収集 | 03-realtime-collection | scripts/preview-realtime.py、docs/data/previews.md、results.md | 締切窓の判定、キャッチアップ、dedup append |
| 4 偏差値化 | 04-hensachi-features | docs/data/estimate.md、scripts/boatrace/index_features.py | hensachi()、waku/racer/exhibit/weather の素点 |
| 5 モーター指数 | 05-motor-ability-index | docs/design/motor_ability_index{,_v2}.md、docs/data/motor_pt.md | z 残差 + 時間減衰 + n_eff 収縮 |
| 6 FeatureContext | 06-feature-context | docs/design/feature_context_refactor.md | セッションインデックス事前計算 |
| 7 強さポイント | 07-strength-index | scripts/build_weights.py、docs/data/estimate.md | fit_one(SLSQP)、寄与分解 |
| 8 買い目 | 08-betting-picks | fun-site packages/batch/src/site-builder/prediction-builder.ts、docs/domain.md | フォーメーション生成 |
| 9 評価指標 | 09-evaluation-metrics | docs/design/ana_prediction.md §13、notebooks/ana_prediction/report.md、registry.py 冒頭 | ペア bootstrap、検出力逆算 |
| 10 レジストリ | 10-predictor-registry | scripts/boatrace/predictors/registry.py、docs/data/estimate.md | PredictorSpec |
| 11 Cloud Run Jobs | 11-cloud-run-jobs | boatracecsv docs/infrastructure.md、infra/*.sh、Dockerfile | run.sh の骨格、Scheduler 設定 |
| 12 沈黙する失敗 | 12-silent-failures | docs/operations.md、docs/infrastructure.md、build_kimarite.py | 不変条件チェック |
| 13 fun-site バッチ | 13-fun-site-batch | fun-site docs/{architecture,batch,infrastructure,operations}.md | build-state、event-parser、deploy |
| 14 Astro | 14-astro-pages | fun-site docs/web.md、packages/shared/src/predictors.ts | PredictorSpec(TS)、spec 駆動描画 |
| 15 予想図 | 15-start-diagram | packages/web/src/lib/start-diagram.ts、components/StartPredictionDiagram.astro | 艇身換算と座標系 |
| 16 説明可能性 | 16-explainability | fun-site docs/domain.md §1、docs/architecture.md 2026-08-23、検算ページ | Python round の偶数丸め移植 |
| 17 ダッシュボード | 17-stats-dashboard | fun-site docs/batch.md(aggregator)、docs/web.md | bigHitPer10kYen、7 軸集計 |
| 18 ST 推定 | 18-st-estimation | docs/design/st_estimation.md、notebooks/st_estimation/*.md、scripts/boatrace/racer_st.py | EWMA + 収縮 + コース補正 |
| 19 スリット | 19-slit-simulation | docs/design/slit_tenkai.md、slit_sim_plan.md、notebooks/slit_sim/report.md | 必要精度の逆算、帯の校正 |
| 20 決まり手 | 20-kimarite-model | docs/design/ana_prediction.md §1〜6、scripts/boatrace/kimarite.py | 多項ロジ学習と係数 CSV 推論 |
| 21 穴予想 | 21-ana-prediction | docs/design/ana_prediction.md §4, §13、kimarite_blend.py、build_suji_table.py | Plackett-Luce、ブレンド |
| 22 おわりに | 22-conclusion | 各設計書の「再挑戦条件」「将来課題」 | なし |
| 23 付録 | 23-appendix | docs/data/README.md | なし(表) |

## 文体・記法

- 章の冒頭に「この章で学ぶこと」(ML の概念 / システムの要素 を 2 列で)を置く。
- 実測値には必ず時点(2026-08)と母数 n を添える。
- コードブロックは Python は `python`、TypeScript は `ts`、シェルは `bash`。ファイル名は `:ファイル名` で付ける。
- 図は `/images/boatrace-ml-system/` に置く(未作成)。
- 各章末に「元資料」と「演習」を置く。演習は boatracecsv.github.io の公開 CSV だけで解けるものにする。

## 執筆メモの扱い

各章ファイル末尾の `## 執筆メモ` セクションは、本文を書き終えたら削除する。
