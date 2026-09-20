# 執筆計画: 機械学習システムの設計と運用 ― ボートレース予想サイトの開発で学ぶデータ収集・モデル・評価・配信

Zenn book `books/boatrace-ml-system/` の執筆計画。章の骨格は各章ファイルに書いてあり、
このファイルは全章に共通する方針と、章 → 元資料 → 掲載コードの対応表を持つ。

## 決定事項(2026-09-19)

| 項目 | 決定 |
| --- | --- |
| タイトル | 『機械学習システムの設計と運用 ― ボートレース予想サイトの開発で学ぶデータ収集・モデル・評価・配信』(2026-09-19 に「ボートレース予想AIを作って運用する」から変更) |
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
fun-site のライセンスは MIT(2026-09-19 に Private から変更)。両リポジトリとも GitHub リンクで実装を参照する。

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

## 執筆手順(章ごと)

1. 骨格ファイルの節構成に従い、本文を日本語で書く(目安 8,000〜15,000 字)。
2. 数値は元資料から引き、時点(2026-08)と母数 n を添える。元資料にない数値は書かない。
3. 簡略版コードは実装から本質だけを抜き、Python は実際に動かして確認する。
4. 「元資料」は GitHub の `blob/main/<path>` リンクにし、パスがローカルに存在することを確認する。
5. 「演習」は公開 CSV だけで解けるものにする。
6. 末尾の `## 執筆メモ` を削除する。
7. 章ごとにコミットする。
- 表示名: registry.py は v1_basic=A君予想、fun-site predictors.ts は 本命予想。本文は fun-site の表示名「本命予想」で統一済み(第 10 章の系譜表に registry 名を併記)

## 進捗(2026-09-19)

- 全 24 章(第 0〜23 章)の本文を執筆・コミット済み。
- 全章合計 約 84 万字(コード込み)。
- 画像 35 枚は作成済み(2026-09-19)。`images/boatrace-ml-system/` に PNG、生成ソースは `docs/books/boatrace-ml-system/images-src/`(matplotlib の .py、HTML/SVG + headless Chrome の .html と render.py / build.sh、サイトのスクリーンショットは screenshots.js)。一覧:

  - 第 00 章: /images/boatrace-ml-system/overview.png
  - 第 01 章: /images/boatrace-ml-system/01-kimarite.png
  - 第 01 章: /images/boatrace-ml-system/01-problem-setting.png
  - 第 01 章: /images/boatrace-ml-system/01-slit-formation.png
  - 第 02 章: /images/boatrace-ml-system/02-scraper-layers.png
  - 第 02 章: /images/boatrace-ml-system/02-three-stages.png
  - 第 03 章: /images/boatrace-ml-system/03-realtime-cycle.png
  - 第 04 章: /images/boatrace-ml-system/04-hensachi-pipeline.png
  - 第 05 章: /images/boatrace-ml-system/motor-pt-pipeline.png
  - 第 05 章: /images/boatrace-ml-system/motor-shrinkage-curve.png
  - 第 06 章: /images/boatrace-ml-system/feature-context-io.png
  - 第 07 章: /images/boatrace-ml-system/07-contribution-decomposition.png
  - 第 07 章: /images/boatrace-ml-system/07-weights-by-stadium.png
  - 第 08 章: /images/boatrace-ml-system/08-formation.png
  - 第 09 章: /images/boatrace-ml-system/09-ci-halfwidth-vs-n.png
  - 第 09 章: /images/boatrace-ml-system/09-metric-roles.png
  - 第 10 章: /images/boatrace-ml-system/10-registry-consumers.png
  - 第 11 章: /images/boatrace-ml-system/11-cloud-run-jobs.png
  - 第 12 章: /images/boatrace-ml-system/silent-failures-cone-window.png
  - 第 12 章: /images/boatrace-ml-system/silent-failures-timeline.png
  - 第 13 章: /images/boatrace-ml-system/13-realtime-chain.png
  - 第 14 章: /images/boatrace-ml-system/astro-pages-data-flow.png
  - 第 15 章: /images/boatrace-ml-system/15-one-mark.png
  - 第 15 章: /images/boatrace-ml-system/15-start-prediction.png
  - 第 15 章: /images/boatrace-ml-system/15-start-result.png
  - 第 16 章: /images/boatrace-ml-system/16-ai-evaluation-chart.png
  - 第 16 章: /images/boatrace-ml-system/16-reproducibility-map.png
  - 第 17 章: /images/boatrace-ml-system/17-stats-page.png
  - 第 18 章: /images/boatrace-ml-system/racer-st-daily-update.png
  - 第 18 章: /images/boatrace-ml-system/st-oracle-floor.png
  - 第 19 章: /images/boatrace-ml-system/slit-sim-band-coverage.png
  - 第 19 章: /images/boatrace-ml-system/slit-sim-retreat-lines.png
  - 第 20 章: /images/boatrace-ml-system/kimarite-calibration.png
  - 第 20 章: /images/boatrace-ml-system/kimarite-pipeline.png
  - 第 21 章: /images/boatrace-ml-system/ana-prediction-pipeline.png

- 2026-09-20: レビュー完了、`published: true` に変更。
