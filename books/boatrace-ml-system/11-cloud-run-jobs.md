---
title: "Cloud Run Jobs で動かす"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 学習(月次)・日次推論・直前推論の 3 種類のジョブに分ける |
| システム | GitHub Actions の schedule が間引かれる問題、1 イメージ 3 ジョブ、sparse-checkout、Secret Manager、Cloud Scheduler、IAM、コスト |

## 1. なぜ GitHub Actions をやめたか

`schedule:` は混雑時に間引かれ、5 分粒度でも実質 1 時間に 1 回しか発火しなかった。2 分更新には使えない。

## 2. 1 イメージ・3 ジョブ

| Job | cron(Asia/Tokyo) | entrypoint | リソース |
| --- | --- | --- | --- |
| preview-realtime | `*/2 8-22 * * *` | `infra/run.sh` | 1 vCPU / 1Gi / 300s |
| daily-sync | `30 7 * * *` | `infra/run-daily-sync.sh` | 2 vCPU / 2Gi / 3600s |
| monthly-weights | `0 6 1 * *` | `infra/run-monthly-weights.sh` | 2 vCPU / 2Gi / 3600s |

`--command` で切り替えるだけなので、ビルドとデプロイは 1 本の cloudbuild.yaml。

## 3. リポジトリを丸ごと clone しない

- リポジトリは約 5GB。`git clone --depth 1 --filter=blob:none` + cone-mode sparse-checkout で必要なパスだけ取る
- ジョブごとに cone が違う(第 12 章の事故の伏線)
- PAT は Secret Manager から、実行 SA に読み取り権限を付ける

## 4. セットアップ手順

- API 有効化 → Artifact Registry → SA 作成 → Secret → IAM → 初回ビルド → Scheduler → 動作確認
- Cloud Build のデフォルト SA に Cloud Run Jobs のデプロイ権限が要る(典型的な失敗ログ付き)
- `run.sh` の骨格を 50 行で示す

## 5. 冪等性と再実行

`parallelism=1 tasks=1 max-retries=0`。CSV はレースコードで dedup、GCS は MD5 dedup なので、再実行はいつでも安全。

## 6. コスト

preview-realtime 約 5,400 実行/月 × 平均 30 秒、daily-sync 30 回 × 約 22 分、monthly-weights 1 回。合算で無料枠 + 数十円/月。Scheduler は 3 ジョブまで無料で、ちょうど 3 本。

## 元資料

- boatracecsv `docs/infrastructure.md`、`infra/run.sh`、`run-daily-sync.sh`、`run-monthly-weights.sh`、`infra/Dockerfile`、`infra/cloudbuild.yaml`、`docs/operations.md`

## 演習

自分の GCP プロジェクトで、公開 CSV を 1 日分ダウンロードして集計するだけの Cloud Run Job を作り、Scheduler から起動する。

## 執筆メモ

- gcloud コマンドは docs/infrastructure.md からそのまま。プロジェクト ID は変数化する。
