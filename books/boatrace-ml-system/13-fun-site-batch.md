---
title: "Pub/Sub から静的サイトへ: fun-site のバッチ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 推論結果(CSV)を受け取る側は何を再計算し、何をしないか |
| システム | GCS ミラーと Pub/Sub、Eventarc → Workflows → Cloud Run Job、早期 return、フルリビルドの判断、OOM 回避、Cache-Control、rsync の事故 |

## 1. 上流からの通知

- boatracecsv の gcs_publisher が当日 CSV を GCS に MD5 dedup でミラーし、1 実行 1 メッセージだけ Pub/Sub に publish
- payload: `raceDate` / `trigger`(daily-bootstrap / realtime)/ `updatedRaces[]` / `gcsPrefix`

## 2. なぜ Workflow を挟むか

Terraform google provider 6.x の Eventarc trigger は Cloud Run Service しか指定できず Job を直接叩けない。Workflow がメッセージを `containerOverrides.args` に載せ、`event-parser.ts` が `argv[2]` → `PUBSUB_MESSAGE` → `CE_DATA` の順で復元する。

## 3. パイプライン

```
event-parser → build-state check → fetcher → prediction-builder → aggregator → site-builder(astro build → deploy)
```

## 4. 早期 return

- 全 CSV の GCS object generation を `_meta/last-build.json` に記録し、次回すべて一致なら即終了
- `updatedRaces` が空なら手前で skip。2 分毎に起動されるジョブの、コストの肝
- 差分ビルドはしない。Astro SSG の依存が当日分に広く及ぶため毎回フルリビルド
- 簡略版コード(TypeScript、build-state、50 行)

## 5. OOM を避ける射影

- RacePrediction は 1 件 100KB 超。数か月分を載せると 2Gi コンテナのヒープ上限を超える
- 集計に必要な項目だけ抜いた PredictionDigest に射影し、日別に GCS にキャッシュ。スキーマ変更時はバージョンを上げる

## 6. デプロイの落とし穴

- Cache-Control を手動で付ける: `.html` = no-cache、`_astro/` = immutable 1 年、その他 = 1 時間。付けないと古いトップが配信され続ける
- 過去日 HTML を消さない rsync。`_astro/` を削除対象から外す前に、過去ページが消えた CSS ハッシュを参照して 404 になった事故と復旧スクリプト

## 元資料

- fun-site `docs/architecture.md`、`docs/batch.md`、`docs/infrastructure.md`、`docs/operations.md`
- `packages/batch/src/{pipeline,build-state,event-parser}.ts`、`aggregator/prediction-digest.ts`、`site-builder/deploy.ts`

## 演習

Pub/Sub メッセージを手で JSON にして `pnpm --filter @fun-site/batch run start` に渡し、早期 return が効くことをログで確認する。

## 執筆メモ

- Terraform の構成は infrastructure.md のファイル別責務表をそのまま載せる。
