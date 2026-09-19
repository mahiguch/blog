---
title: "Cloud Run Jobs で動かす"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML(運用の形として) | 学習(月次)・日次推論・直前推論の 3 種類のジョブに分ける理由。重みは月に 1 回しか変わらず、特徴量は「朝に揃うもの」と「締切 5 分前にしか無いもの」に分かれ、境界日(毎月 1 日)には同じ重みで計算したい、という要件がそのままジョブの分割と起動順になる |
| システム(GCP 上の実装として) | GitHub Actions の `schedule:` が間引かれる問題、1 イメージ 3 ジョブ、部分クローンと cone-mode sparse-checkout、Secret Manager、Cloud Build → Artifact Registry → Cloud Run Jobs、Cloud Scheduler と IAM、冪等性と再実行、コスト |

第 2 章から第 10 章までで、収集スクリプトと予測モデルが揃いました。この章では、それらを毎日・2 分毎・毎月という 3 つの周期で動かし続けるための土台を作ります。使うのは GCP の Cloud Run Jobs と Cloud Scheduler で、コードは boatracecsv の `infra/` ディレクトリにまとまっています。gcloud コマンドは `docs/infrastructure.md` のものをそのまま使い、プロジェクト ID などは変数にしています。

## 1. なぜ GitHub Actions をやめたか

もともと 3 つのジョブはすべて GitHub Actions の `schedule:` イベントで動いていました。リポジトリと同じ場所に置けて、Secrets の管理も不要で、無料枠に収まる。個人開発の定期実行としては最初に選ぶべき選択肢です。

問題は精度でした。GitHub Actions の `schedule:` は混雑時に間引かれ、5 分粒度で書いても事実上 1 時間に 1 回しか発火しないことがあります(`docs/infrastructure.md` 冒頭)。日次や月次のジョブなら数十分の遅れは許容できますが、第 3 章で見た直前バッチは「締切 5 分前に公開される直前情報を、締切前に取る」仕事です。1 時間に 1 回では、その日のほとんどのレースを取りこぼします。第 3 章の締切窓が 9 分と広めに取ってあるのは、この時代の名残でした。

そこで、より精度の高いトリガとして Cloud Scheduler から Cloud Run Jobs を直接叩く構成に移しました。Cloud Scheduler は cron 式どおりに発火し、Cloud Run Jobs はコンテナを 1 回実行して終了するサービスです。「2 分毎に 5 分以内で終わるスクリプトを 1 本走らせる」という要件に、この 2 つの組み合わせは過不足なく合います。

移行後も `docs/operations.md` によれば `.github/workflows/preview-realtime.yml` は `workflow_dispatch`(手動起動)だけを残してあり、Cloud Run 側に障害が出たときに GitHub の UI から 1 回だけ起動するフォールバックになっています。daily-sync と monthly-weights のワークフローは移行完了後に削除する方針で、代わりに `gcloud run jobs execute` で開発者端末から起動します(第 5 節)。

:::message
Cloud Run **Jobs** は、HTTP リクエストを受け続ける Cloud Run **Service** とは別物です。Service は常駐してリクエストに応答し、Jobs は起動されるたびにコンテナを 1 回実行して終了します。バッチ処理には Jobs を使い、Web サーバーには Service を使います。第 13 章で、Eventarc が Job を直接起動できないという制約に当たりますが、それもこの違いから来ています。
:::

## 2. 1 イメージ・3 ジョブ

### 2.1 3 種類のジョブ

| Job | cron(Asia/Tokyo) | entrypoint | リソース | 概要 |
| --- | --- | --- | --- | --- |
| `preview-realtime` | `*/2 8-22 * * *` | `infra/run.sh` | 1 vCPU / 1 GiB / 300 秒 | 直前情報の収集 + index の realtime 行更新 + 結果・払戻の取り込み(第 3 章) |
| `daily-sync` | `30 7 * * *` | `infra/run-daily-sync.sh` | 2 vCPU / 2 GiB / 3,600 秒 | 当日の出走表・近況・モーター成績の収集 + daily index 生成(第 2 章、第 6 章) |
| `monthly-weights` | `0 6 1 * *` | `infra/run-monthly-weights.sh` | 2 vCPU / 2 GiB / 3,600 秒 | 直近 6 か月で場ごとの重みを再学習 + 静的テーブル(スジ表・決まり手係数など)の再生成(第 7 章、第 20 章) |

ML の言葉に直すと、monthly-weights が**学習**、daily-sync が**日次推論**、preview-realtime が**直前推論**です。1 つのジョブにまとめない理由は 3 つあります。

1. **重みは月に 1 回しか変わらない。** 第 7 章の強さポイントの重みは直近 6 か月の結果から SLSQP で学習しますが、1 日分のデータが増えても重みはほとんど動きません。毎日学習し直すのはコストの無駄で、しかも日ごとに微妙に違う重みで予想が出ると、第 9 章の評価が「モデルの差」と「重みの揺れ」を区別できなくなります
2. **特徴量が揃う時刻が違う。** 出走表・近況・モーター成績は朝に揃いますが、展示タイム・進入コース・気象は締切 5 分前にしか手に入りません。朝の時点で全レースの暫定値(状態 = `daily`。展示・気象は偏差値 50 で補完)を出し、締切前に該当レースだけ実値で更新する(状態 = `realtime`)、という 2 段階が自然です
3. **境界日に同じ重みで計算したい。** 毎月 1 日は monthly-weights が JST 06:00、daily-sync が 07:30、preview-realtime が 08:00 から動きます。学習を先に終わらせておくことで、その日の daily 行と realtime 行が同じ月の重みで計算されます。学習データは `data/results/realtime/` に締切後 3〜30 分で追記されていくので(第 3 章)、06:00 の時点で前月最終日の結果はすでに揃っています

![3 ジョブの起動と出力](/images/boatrace-ml-system/11-cloud-run-jobs.png)
<!-- 図: 上段に Cloud Scheduler の 3 本(preview-realtime-daytime */2 8-22、daily-sync 30 7、monthly-weights 0 6 1)。それぞれ OIDC トークン付き HTTP POST で Cloud Run Jobs の 3 Job に矢印。3 Job は 1 つの Docker イメージ(Artifact Registry)から --command で分岐していることを枠で示す。各 Job から GitHub(git push)への矢印。preview-realtime と daily-sync からだけ GCS ミラーと Pub/Sub topic への矢印を出し、monthly-weights は git push のみ。Secret Manager(github-token)から 3 Job へ点線。右下に毎月 1 日のタイムライン 06:00 → 07:30 → 08:00〜22:58。 -->

### 2.2 なぜイメージは 1 本か

3 つのジョブは同じ `requirements.txt` に依存し、同じ `scripts/boatrace` パッケージを読みます。違うのは起動時に走らせるシェルスクリプトだけなので、Docker イメージは 1 本にまとめ、Cloud Run Job 側の `--command` で切り替えています。

```dockerfile:infra/Dockerfile(要点)
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 TZ=Asia/Tokyo

# git: 実行時に clone / commit / push する。tini: PID 1 としてシグナルを扱い、
# Cloud Run のタイムアウトでコンテナが素直に止まるようにする
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates tzdata tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# エントリポイントのシェルだけを焼き込む。Python ソースは実行時に clone する
COPY --chmod=0755 infra/run.sh                 /app/run.sh
COPY --chmod=0755 infra/run-daily-sync.sh      /app/run-daily-sync.sh
COPY --chmod=0755 infra/run-monthly-weights.sh /app/run-monthly-weights.sh

RUN useradd --create-home --uid 1000 runner && mkdir -p /workspace && chown -R runner:runner /workspace
USER runner
WORKDIR /workspace

# ENTRYPOINT は tini のみ。どのスクリプトを走らせるかは Job の --command で決める
ENTRYPOINT ["/usr/bin/tini", "--"]
```

このイメージには Python の依存関係とシェルスクリプトしか入っていません。`scripts/` 配下の Python ソースは**実行時に clone** します。イメージをビルドし直すのは依存関係かシェルスクリプトが変わったときだけで、Python の修正や `data/` の更新は main に push するだけで次の実行から反映されます。逆に言うと、`run.sh` の sparse-checkout リストを変えたときはイメージの再ビルドが必要です。この非対称は `docs/infrastructure.md` の「更新手順」に表としてまとまっています。

| 変更したファイル | 必要なアクション |
| --- | --- |
| `scripts/requirements.txt`、`infra/Dockerfile` | イメージ再ビルド + 全 Job 更新 |
| `scripts/*.py`(Python ソース) | 不要(Job は実行時に最新 main を clone する)。ただし `docs/infrastructure.md` の表は保守的に「再ビルド」としている |
| `infra/run*.sh` | イメージ再ビルド + 該当 Job 更新 |
| `infra/cloudbuild.yaml` | 再ビルドだけで反映(自身が実行される) |
| `data/**` のみ | 不要(Job は実行時に最新 main を pull する) |

:::message
Python ソースを実行時に clone する設計は、「イメージが古くてもコードは常に最新」という利点と引き換えに、「イメージ内のシェルとリポジトリ内の Python がずれる」可能性を持ち込みます。実際、レジストリに予想者を追加したのに `run.sh` の `ACTIVE_PREDICTORS` を更新し忘れ、古いイメージが新しい予想者の index CSV を checkout しない、という事故が典型として記録されています(`preview_realtime_index_skipped reason=index_csv_missing`)。
:::

## 3. リポジトリを丸ごと clone しない

### 3.1 部分クローン + cone-mode sparse-checkout

boatracecsv リポジトリは `data/` と `models/` が大半を占めて約 5 GB あります(`run.sh` のコメント)。preview-realtime Job のメモリは 1 GiB で、素朴に `git clone` すると OOM で落ちます。2 分毎に 5 GB を引くのは時間的にも成り立ちません。

そこで 2 段構えで取得量を絞っています。

1. **部分クローン**: `git clone --depth 1 --filter=blob:none --no-checkout`。コミットとツリー(ディレクトリ構造)だけを取り、ファイル本体(blob)は取りません
2. **cone-mode sparse-checkout**: `git sparse-checkout set <paths...>` で「このディレクトリ配下だけ作業ツリーに展開する」と宣言してから `git checkout` します。blob は展開されるファイルの分だけ、その場で取得されます

cone-mode は、パスをディレクトリ単位で指定する sparse-checkout のモードです。指定したディレクトリの配下は再帰的に全部入り、それ以外は作業ツリーに現れません。パターンマッチを使う従来モードより速く、`git` 自身が推奨しています。

preview-realtime の cone は「当月分」を単位にしています。`data/previews/tkz/2026/09` のように `YYYY/MM` までを指定すれば、その月の日別 CSV だけが入ります。`data/programs/motor_stats/` だけは前月分も入れています。月初の数日はモーター期成績が当月ファイルに無く、7 日前まで遡って読む fallback があるためです。

3 つのジョブは読み書きするファイルが違うので、cone も 3 通りです。

| Job | cone の特徴 |
| --- | --- |
| `preview-realtime` | 当月の previews / results / index と、静的テーブル。展開後は数十 MB |
| `daily-sync` | 当月の programs 一式に加え、モーターptの 90 日ルックバックが触る月の `race_cards` と `title`(月を bash で列挙する。5/1 の 90 日前は 1/31 なので固定月数にはしない) |
| `monthly-weights` | 対象月 + 過去 7 か月の月別ディレクトリに加え、`data/results/realtime/` や `data/previews/{stt,tkz,sui}/` は全履歴。`race_cards` だけは checkout 後に `git sparse-checkout add` で必要な月を足す 2 段階 |

monthly-weights の cone が最も広く、2026 年 8 月の実測で作業ツリーと `.git` を合わせて約 321 MB です。Cloud Run の `/tmp` は tmpfs で、checkout したサイズがそのままメモリを消費します。`race_cards` を丸ごと入れると 42 MB の死荷重(結果 CSV が始まる 2025 年 11 月より前の月)が乗るので、`data/results/realtime/` に実在する月を `ls` で列挙して、その月の `race_cards` だけを後から足しています。epoch を定数で持たないので、履歴が伸びても backfill されても追従します。

:::message alert
cone-mode には重要な性質があります。**cone の外のパスに書いたファイルは `git add` に無視され、エラーになりません。** スクリプトが正常終了し、ログにも書き込み完了と出て、しかしリポジトリには何も残らない、という状態になります。逆に `git add` に cone 外のパスが 1 つでも混ざると `git add` 全体が非 0 で終了し、その回のコミットが丸ごと落ちます。boatracecsv では両方の型の事故が実際に起きました。詳細は第 12 章で扱いますが、この章の時点で「出力先を増やしたら cone と `git add` の両方に足す」という規則を覚えておいてください。
:::

### 3.2 run.sh の骨格

preview-realtime のエントリポイント `infra/run.sh` は 180 行ありますが、本質は「部分クローン → sparse-checkout → 認証設定 → Python 実行」の 4 段です。骨格だけを抜き出すと次のようになります。

```bash:infra/run.sh(骨格)
#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '[run.sh %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
trap 'log "FAILED (exit=$?) at line $LINENO"' ERR

# GITHUB_TOKEN は Cloud Run Job の --set-secrets で Secret Manager から注入される
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required (mount Secret Manager secret github-token)}"
GITHUB_REPO="${GITHUB_REPO:-BoatraceCSV/boatracecsv.github.io}"
GIT_BRANCH="${GIT_BRANCH:-main}"

WORKDIR="$(mktemp -d -t preview-realtime.XXXXXX)"
trap 'rm -rf "${WORKDIR}"' EXIT
cd "${WORKDIR}"

REMOTE_WITH_TOKEN="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"
REMOTE_PUBLIC="https://github.com/${GITHUB_REPO}.git"

# csv_path_for() が JST の日付でパスを切るので、当月と前月も JST で求める
TODAY_YM=$(TZ=Asia/Tokyo date +'%Y/%m')
PREV_YM=$(TZ=Asia/Tokyo date -d "$(TZ=Asia/Tokyo date +'%Y-%m-15') -1 month" +'%Y/%m')
ACTIVE_PREDICTORS=(v1_basic v10_kimarite)   # registry.active_predictors() と同期させる

# 1. 部分クローン: コミットとツリーだけ。blob は checkout 時に必要な分だけ取る
log "Cloning ${REMOTE_PUBLIC} (partial+sparse, ym=${TODAY_YM}, prev=${PREV_YM})"
git clone --depth 1 --filter=blob:none --no-checkout --no-tags \
  --single-branch --branch "${GIT_BRANCH}" "${REMOTE_WITH_TOKEN}" repo
cd repo

# 2. cone-mode sparse-checkout: preview-realtime.py が読み書きするパスだけ
sparse_paths=(
  scripts .boatrace data/estimate/stadium
  data/estimate/suji/tables data/estimate/kimarite/tables
  "data/programs/recent_national/${TODAY_YM}" "data/programs/recent_local/${TODAY_YM}"
  "data/programs/motor_stats/${TODAY_YM}" "data/programs/motor_stats/${PREV_YM}"
  "data/previews/tkz/${TODAY_YM}" "data/previews/stt/${TODAY_YM}" "data/previews/sui/${TODAY_YM}"
  "data/previews/original_exhibition/${TODAY_YM}" "data/previews/tokuten_hayami/${TODAY_YM}"
  "data/previews/od1/${TODAY_YM}" "data/previews/od2/${TODAY_YM}" "data/previews/od3/${TODAY_YM}"
  "data/estimate/kimarite/${TODAY_YM}" "data/estimate/kimarite/picks/${TODAY_YM}"
  "data/results/realtime/${TODAY_YM}" "data/results/payouts/${TODAY_YM}"
  "data/programs/title/${TODAY_YM}" "data/programs/race_cards/${TODAY_YM}"
)
for predictor in "${ACTIVE_PREDICTORS[@]}"; do
  sparse_paths+=("data/estimate/${predictor}/${TODAY_YM}")
done
git sparse-checkout init --cone
git sparse-checkout set "${sparse_paths[@]}"
git checkout "${GIT_BRANCH}"

# 3. push 用の認証。URL 書き換えでトークンを渡し、`git remote -v` には残さない
git config --local user.name  "${GIT_USER_NAME:-preview-realtime-bot}"
git config --local user.email "${GIT_USER_EMAIL:-preview-realtime-bot@users.noreply.github.com}"
git config --local --replace-all "url.${REMOTE_WITH_TOKEN}.insteadOf" "${REMOTE_PUBLIC}"
git remote set-url origin "${REMOTE_PUBLIC}"

# 4. 実行。commit と push は Python 側(boatrace.git_operations)が行う
log "Running scripts/preview-realtime.py ${PREVIEW_EXTRA_ARGS:-}"
python scripts/preview-realtime.py ${PREVIEW_EXTRA_ARGS:-}
log "Done"
```

いくつか設計上の判断があります。

- **トークンを URL に埋めるのは clone の 1 回だけ。** その後 `url.<token付き>.insteadOf <公開URL>` を設定し、`origin` は公開 URL に戻します。Python 側の `git fetch` / `git push` は insteadOf の書き換えで認証され、`git remote -v` やエラーメッセージにトークンが出ません
- **`set -Eeuo pipefail` と `trap ... ERR`。** どこで落ちたかを行番号付きでログに残し、非 0 で終了します。Cloud Run Jobs は非 0 終了を失敗として記録するので、Cloud Logging で失敗した実行を絞り込めます
- **`ACTIVE_PREDICTORS` は手で同期する。** 第 10 章のレジストリ `active_predictors()` と同じ ID を並べます。bash から Python のレジストリを読むこともできますが、clone 前に cone を決める必要があるので、シェルに定数を持たせています。ズレたときの症状は第 2 節の `:::message` のとおりです

`run-daily-sync.sh` と `run-monthly-weights.sh` も同じ骨格で、違いは cone の中身と、Python 実行の後に bash 側で `git add` → `git commit` → `git push` を行う点です(`build_index.py` や `build_weights.py` は CSV を書くだけで自分では commit しません)。

### 3.3 PAT は Secret Manager から

git push には GitHub の認証が要ります。GitHub Actions では自動で `GITHUB_TOKEN` が渡されましたが、Cloud Run ではこちらで用意します。使うのは fine-grained PAT(Personal Access Token)で、対象リポジトリを boatracecsv だけに絞り、権限は `Contents: Read and write` のみ、有効期限は 90 日にしています。

トークンは Secret Manager に `github-token` という名前で登録し、Job の実行サービスアカウント(Runner SA)にだけ `roles/secretmanager.secretAccessor` を付けます。Job 側は `--set-secrets=GITHUB_TOKEN=github-token:latest` で環境変数として受け取ります。`:latest` 参照なので、ローテート時は `gcloud secrets versions add` で新バージョンを積むだけで、Job の再デプロイは不要です。3 Job が同じ Secret を参照しているので 1 回で済みます。

## 4. セットアップ手順

`docs/infrastructure.md` の「ワンタイム セットアップ」を、変数を定義してから順に実行します。Cloud Shell か、`gcloud auth login` 済みの端末で行います。

### 4.1 共通変数と API

```bash
export PROJECT_ID=<your-project-id>
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
export REGION=asia-northeast1
export AR_REPO=containers
export IMAGE=preview-realtime
export JOB_NAME=preview-realtime
export RUNNER_SA=preview-realtime-runner
export INVOKER_SA=preview-realtime-invoker
export SECRET_NAME=github-token
export GITHUB_REPO=BoatraceCSV/boatracecsv.github.io

gcloud config set project "$PROJECT_ID"

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com logging.googleapis.com
```

### 4.2 Artifact Registry、サービスアカウント、Secret

```bash
# イメージの置き場所
gcloud artifacts repositories create "$AR_REPO" \
  --repository-format=docker --location="$REGION" \
  --description="Container images for boatrace automation"

# Job を実行する ID(Runner)と、Scheduler が Job を叩く ID(Invoker)は分ける
gcloud iam service-accounts create "$RUNNER_SA" \
  --display-name="preview-realtime Cloud Run Job runner"
gcloud iam service-accounts create "$INVOKER_SA" \
  --display-name="Cloud Scheduler invoker for preview-realtime"

# GitHub の fine-grained PAT を Secret Manager に登録
printf '%s' '<github-fine-grained-pat>' | \
  gcloud secrets create "$SECRET_NAME" --replication-policy=automatic --data-file=-

# Runner SA にだけ読み取りを許可
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:${RUNNER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor

# Runner SA は Cloud Logging に書く
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNNER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/logging.logWriter
```

Runner と Invoker を分けるのは最小権限のためです。Invoker は「Job を起動する」権限(`roles/run.invoker`)しか持たず、Secret を読めません。Runner は Secret と Logging(および fun-site 側で付与される GCS / Pub/Sub)の権限を持ちますが、Job を起動する権限はありません。どちらかが漏れても、できることが限られます。

### 4.3 Cloud Build のサービスアカウントに権限を足す

ここが最初にはまりやすい箇所です。`cloudbuild.yaml` の最後のステップは `gcloud run jobs deploy` で Cloud Run Job を作成・更新します。この gcloud を実行しているのは**あなたではなく Cloud Build のサービスアカウント**なので、そちらに権限が要ります。足りないと、ビルドは次のログで落ちます。

```
BUILD FAILURE: Build step failure: build step 3
"gcr.io/google.com/cloudsdktool/cloud-sdk:slim" failed:
step exited with non-zero status: 1
```

このメッセージだけでは原因が分かりません。実エラーは Cloud Build のログ末尾にあります。

```bash
BUILD_ID=$(gcloud builds list --limit=1 --project="$PROJECT_ID" --format='value(id)')
gcloud builds log "$BUILD_ID" --project="$PROJECT_ID" | tail -60
```

末尾に `Permission 'run.jobs.create' denied` と出ていれば `roles/run.developer` が、`Permission 'iam.serviceaccounts.actAs' denied on service account preview-realtime-runner@...` と出ていれば Runner SA への `roles/iam.serviceAccountUser` が足りません。後者は「Job に Runner SA を attach してよいか」の権限で、忘れやすい方です。

```bash
# Cloud Build が使う SA。新しいプロジェクトでは Compute のデフォルト SA が使われる
CB_SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
# 古いプロジェクトでは ${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com のことがある。
# `gcloud builds list --format='table(id,createTime,createdBy)'` の createdBy で確認できる

# Cloud Run Jobs を deploy / update する権限
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="$CB_SA" --role=roles/run.developer

# Job に Runner SA を attach する権限
gcloud iam service-accounts add-iam-policy-binding \
  "${RUNNER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="$CB_SA" --role=roles/iam.serviceAccountUser
```

### 4.4 cloudbuild.yaml と初回ビルド

`infra/cloudbuild.yaml` は「ビルド → push → 3 Job の deploy」を 1 本にまとめたパイプラインで、Job のスペック(CPU、メモリ、タイムアウト、環境変数)の唯一の情報源でもあります。要点だけ示します。

```yaml:infra/cloudbuild.yaml(要点)
substitutions:
  _REGION: asia-northeast1
  _AR_REPO: containers
  _IMAGE: preview-realtime          # 3 Job 共通。歴史的経緯で名前は preview-realtime のまま
  _PROJECT_ID: <your-project-id>
  _RUNNER_SA: preview-realtime-runner
  _SECRET_NAME: github-token
  _GCS_CSV_BUCKET: <csv-mirror-bucket>
  _PUBSUB_TOPIC: projects/<your-project-id>/topics/fun-site-realtime-completed

images:
  - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:${SHORT_SHA}'
  - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:latest'

steps:
  - id: build
    name: gcr.io/cloud-builders/docker
    env: [DOCKER_BUILDKIT=1]         # Dockerfile の COPY --chmod に必要
    args: [build, --file=infra/Dockerfile,
           --tag=${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:${SHORT_SHA},
           --tag=${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:latest,
           --cache-from=${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:latest, .]
  - id: push-sha
    name: gcr.io/cloud-builders/docker
    args: [push, '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:${SHORT_SHA}']
  - id: push-latest
    name: gcr.io/cloud-builders/docker
    args: [push, '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:latest']

  # create-or-update。初回は Job を作成し、2 回目以降はイメージを差し替える
  - id: deploy-job
    name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
    entrypoint: gcloud
    args:
      - run
      - jobs
      - deploy
      - preview-realtime
      - --image=${_REGION}-docker.pkg.dev/${_PROJECT_ID}/${_AR_REPO}/${_IMAGE}:${SHORT_SHA}
      - --region=${_REGION}
      - --project=${_PROJECT_ID}
      - --service-account=${_RUNNER_SA}@${_PROJECT_ID}.iam.gserviceaccount.com
      - --command=/app/run.sh
      - --set-secrets=GITHUB_TOKEN=${_SECRET_NAME}:latest
      - --set-env-vars=GITHUB_REPO=BoatraceCSV/boatracecsv.github.io,GIT_BRANCH=main,BOATRACE_GCS_CSV_BUCKET=${_GCS_CSV_BUCKET},BOATRACE_PUBSUB_TOPIC=${_PUBSUB_TOPIC}
      - --max-retries=0
      - --task-timeout=300s
      - --parallelism=1
      - --tasks=1
      - --cpu=1
      - --memory=1Gi

  # daily-sync:      --command=/app/run-daily-sync.sh,      --task-timeout=3600s, --cpu=2, --memory=2Gi
  # monthly-weights: --command=/app/run-monthly-weights.sh, --task-timeout=3600s, --cpu=2, --memory=2Gi
  #                  (GCS / Pub/Sub の環境変数は渡さない。weights は git push だけで配る)
  - id: deploy-job-daily-sync
    ...
  - id: deploy-job-monthly-weights
    ...

timeout: 1800s
```

読むときのポイントは 3 つです。

- **イメージは `:SHORT_SHA` と `:latest` の 2 タグ。** Job は `:SHORT_SHA` を指すので、問題が出たら前の SHA に `gcloud run jobs deploy --image=...:<PREV_SHA>` で戻せます。`:latest` は次のビルドの `--cache-from` に使います
- **`gcloud run jobs deploy` は create-or-update。** Job が無ければ作り、あれば更新します。初回セットアップと日常の更新が同じコマンドで済み、`cloudbuild.yaml` が Job のスペックの唯一の情報源になります
- **`--set-env-vars` は列挙したキーで全置換。** GCS バケットや Pub/Sub トピックを手で `--update-env-vars` していた時期があり、ビルドのたびに値が消えていました。`substitutions` に持たせて毎回流し込む形に改めた経緯があります

初回ビルドを実行します。ビルドは典型的に 2〜4 分で、完了時点で 3 つの Job が作成されています。

```bash
gcloud builds submit \
  --config infra/cloudbuild.yaml \
  --substitutions=SHORT_SHA=$(git rev-parse --short HEAD) \
  --project "$PROJECT_ID"

gcloud run jobs describe "$JOB_NAME" --region="$REGION" \
  --format='value(name,template.template.containers[0].image)'
```

`main` への push で自動ビルドしたい場合は、`infra/**,scripts/**` を監視する Cloud Build トリガを作ります(`gcloud builds triggers create github --build-config=infra/cloudbuild.yaml --included-files='infra/**,scripts/**' ...`)。`data/**` だけの commit ではビルドが走らないようにするのが目的です。

### 4.5 Cloud Scheduler の登録

Scheduler は Cloud Run Jobs の `:run` API に HTTP POST を送るだけです。認証は Invoker SA の OIDC トークンで行うので、先に Invoker SA に Job の起動権限を付けます。

```bash
INVOKER_EMAIL="${INVOKER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --region="$REGION" \
  --member="serviceAccount:${INVOKER_EMAIL}" \
  --role=roles/run.invoker

JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

# JST 08:00, 08:02, ..., 22:58
gcloud scheduler jobs create http preview-realtime-daytime \
  --location="$REGION" \
  --schedule="*/2 8-22 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="$JOB_URI" \
  --http-method=POST \
  --oauth-service-account-email="$INVOKER_EMAIL" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --attempt-deadline=60s \
  --description="Preview realtime — JST 08:00-22:59"
```

`--time-zone=Asia/Tokyo` を指定すると cron 式を JST で書けます。GitHub Actions 時代は UTC で `30 22 * * *` と書いていた daily-sync が、`30 7 * * *` と読めるようになります。`--attempt-deadline=60s` は Scheduler が API の応答を待つ時間で、`:run` は実行をキックしてすぐ返るので 60 秒で十分です。Job 自体のタイムアウト(300 秒)とは別物です。

daily-sync と monthly-weights も同じ形で登録しますが、2 点だけ違います。

```bash
gcloud scheduler jobs create http daily-sync \
  --location="$REGION" \
  --schedule="30 7 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/daily-sync:run" \
  --http-method=POST \
  --oauth-service-account-email="$INVOKER_EMAIL" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --attempt-deadline=60s \
  --max-retry-attempts=3 --min-backoff=30s --max-backoff=300s \
  --description="Daily boatrace data sync — JST 07:30"

# 動作確認が済むまで pause しておく
gcloud scheduler jobs pause daily-sync --location="$REGION"
```

1 つ目は `--max-retry-attempts=3` です。Scheduler の発火自体が失敗する(Cloud Run Admin API が 503 を返す)と、リトライ設定が無ければ次の発火は翌日 07:30 で、当日分が丸ごと欠けます。2026-08-29 にこれが実際に起き、daily-sync が走らなかったため当日の `title` / `race_cards` が無く、preview-realtime は成功し続けるのに結果・払戻の対象が 0 件、Pub/Sub も飛ばず fun-site の更新が止まる、という連鎖になりました。git の履歴だけ見ると preview 系の commit が積まれていて正常に見えるのが厄介な点です。preview-realtime にはリトライを付けていません。2 分後に次のサイクルが来るので 1 回の失敗は自然に吸収され、リトライを足すと実行が重なる害の方が大きいためです。

2 つ目は `--paused` で作ってから動作確認し、旧 GitHub Actions の `schedule:` を削除する PR をマージした**後に** resume する、という順序です。両方が同じ日に同じ CSV へ書くと push 競合や行の重複の原因になります。

### 4.6 動作確認

```bash
# 手動で 1 サイクル実行し、完了まで待つ
gcloud run jobs execute "$JOB_NAME" --region="$REGION" --wait

# 直近の実行一覧
gcloud beta run jobs executions list --job="$JOB_NAME" --region="$REGION" --limit=5

# Scheduler を即座に発火させる
gcloud scheduler jobs run preview-realtime-daytime --location="$REGION"

# Cloud Logging で stdout / stderr を読む
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="preview-realtime"' \
  --limit=50 --format='value(timestamp,textPayload)'
```

`run.sh` の `log` 関数が `[run.sh <UTC時刻>] ...` の形で書く行と、Python 側の構造化ログが混ざって出てきます。第 12 章で使う `preview_realtime_index_skipped` や `stage_files_failed` といったイベント名は、この `gcloud logging read` に `jsonPayload.event="..."` を足して絞り込みます。

## 5. 冪等性と再実行

3 つの Job はすべて `--parallelism=1 --tasks=1 --max-retries=0` で動きます。1 実行 1 コンテナ、Cloud Run 側の自動リトライ無し、です。「失敗したらどうするか」を Cloud Run に任せず、ジョブごとに決めています。

| Job | 失敗時 | 理由 |
| --- | --- | --- |
| `preview-realtime` | 何もしない。次のサイクル(2 分後)に任せる | 締切窓が 9 分あり、結果・払戻は catch-up モードで終日再試行する(第 3 章)。リトライは実行の重複を招く |
| `daily-sync` | 翌朝 07:30 の実行で同じ index を再生成して上書き。急ぐなら手動実行 | 各ステップは `run_step` で包み、1 つ失敗しても残りを続行して最後に exit 1 にする(GitHub Actions の `if: always()` の置き換え) |
| `monthly-weights` | 翌月まで自動実行が無いので、手動で追走する | 失敗時のログに `ABORT:` が出る。`TARGET_MONTH` を指定して過去月も再計算できる |

再実行を「いつでも安全」にしているのは、書き込み側の 3 つの性質です。

1. **CSV はレースコードで dedup する。** 第 2 章・第 3 章で見たとおり、追記前に既存行のレースコードを読み、あれば書きません。同じ日に 2 回走っても行は増えません
2. **GCS ミラーは MD5 で dedup する。** 第 13 章の `gcs_publisher` はローカルファイルの MD5 と GCS 上のオブジェクトの MD5 を比べ、一致すればアップロードしません。差分が無ければ Pub/Sub も飛びません
3. **push は fetch + rebase + push。** preview-realtime が 2 分毎に main へ push するので、他の Job が bare push すると non-fast-forward で reject されることが普通にあります。Python 側の `boatrace.git_operations.push()` は fetch → rebase → push を内蔵しており、`run-monthly-weights.sh` の `push_with_rebase` も同じことを最大 5 回、`sleep $((attempt * 2))` のバックオフ付きで行います。3 Job が書くパスは互いに素なので rebase は衝突しない想定で、万一 conflict が出たら abort して fail します(人手調査が必要な異常なので)

`run-daily-sync.sh` の `commit-index` ステップだけは bare push のままで、失敗を `run_step` が握り潰します。当日の index が main に載らない代わりに、翌朝の daily-sync が同じものを再生成して上書きするからです。GCS ミラーと Pub/Sub は git push とは独立に走るので、fun-site への配信は止まりません。

過去日の再計算(backfill)は環境変数の上書きで行います。

```bash
# 特定日の daily-sync をやり直す
gcloud run jobs execute daily-sync --region="$REGION" \
  --update-env-vars=RUN_DATE=2026-05-01 --wait

# 特定月の重みを再学習する
gcloud run jobs execute monthly-weights --region="$REGION" \
  --update-env-vars=TARGET_MONTH=2026-03 --wait
```

`RUN_DATE` / `TARGET_MONTH` はシェルスクリプトの冒頭で読まれ、cone の月リストも含めてすべてがその日付基準で計算されます。ただし preview-realtime の稼働時間帯(JST 08:00〜22:59)に手動再実行を仕掛けると push レースに負けやすいので、可能なら夜間か早朝に行います。

:::message
`gcloud run jobs execute --update-env-vars` は**その実行だけ**の上書き(override)で、Job の定義は変わりません(`gcloud run jobs execute --help`)。既存の環境変数とマージした値でその 1 回の実行が作られるだけなので、backfill の後に何かを戻す必要はありません。Job の定義そのものを変える `gcloud run jobs update --update-env-vars` とは別物で、こちらは次のビルドで `cloudbuild.yaml` の `--set-env-vars` に全置換されるまで残ります。
:::

## 6. コスト

2026 年 8 月時点の実行回数と実測時間から、`docs/infrastructure.md` は次のように見積もっています。

| Job | 実行回数 | 1 実行あたり | リソース |
| --- | --- | --- | --- |
| `preview-realtime` | 180 回/日 × 30 日 ≒ 5,400 実行/月 | 平均 30 秒 | 1 vCPU / 1 GiB |
| `daily-sync` | 30 回/月 | 約 22 分 | 2 vCPU / 2 GiB |
| `monthly-weights` | 1 回/月 | 10〜15 分 | 2 vCPU / 2 GiB |

preview-realtime の「180 回/日」は `docs/infrastructure.md` の見積もりで、5 分毎だった時代の値がそのまま残っていると考えられます。現在の `*/2 8-22 * * *` なら発火は 1 時間 30 回 × 15 時間 = 450 回/日、月 13,500 回です。ただし対象レースが無いサイクルは clone だけして数秒で終わるので、桁としての結論は変わりません。

Cloud Run Jobs は実行中の vCPU 秒とメモリ GiB 秒で課金されます。preview-realtime は回数こそ多いものの 1 回平均 30 秒なので、docs の見積もりで月の合計は 5,400 × 30 秒 = 45 時間・vCPU 程度、450 回/日で数えても 2.5 倍です。daily-sync は 30 × 22 分 × 2 vCPU = 22 時間・vCPU です。合算しても無料枠に収まるか、超えても数十円/月の水準です。Cloud Scheduler は 3 ジョブまで無料で、現在ちょうど 3 本です。4 本目からは 1 ジョブあたり月 $0.10 かかります。

コストより先に気にすべきはメモリの上限です。monthly-weights は checkout 約 321 MB(tmpfs)に加えて `build_kimarite.py` の peak RSS が 578 MB(43,595 レース)で、合わせて約 0.9 GB を 2 GiB の中で使っています。全履歴で学習するスクリプトなので、1 レースあたり約 9.6 KB、月あたり約 42 MB ずつ増え、約 2 年で上限に近づく計算です。`docs/infrastructure.md` は「peak RSS が 1.2 GB を超えたら `cloudbuild.yaml` の `deploy-job-monthly-weights` を 4 GiB に上げる」と閾値を決めています。数値を書き留めて閾値を決めておくのは、第 12 章で扱う「気づかないうちに壊れる」事故を、リソースについても防ぐためです。

Cloud Build は 1 回 2〜4 分で、`infra/**,scripts/**` に変更があったときだけ走ります。`data/**` の更新は開催日に何度も commit されますが、ビルドを起こしません。

## 元資料

- boatracecsv [`docs/infrastructure.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md) — アーキテクチャ、sparse-checkout 対象、ワンタイムセットアップ、更新手順、運用メモ(コスト)、トラブルシュート
- boatracecsv [`docs/operations.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/operations.md) — Workflows 節(GitHub Actions のフォールバック)
- boatracecsv [`infra/run.sh`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run.sh)、[`infra/run-daily-sync.sh`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-daily-sync.sh)、[`infra/run-monthly-weights.sh`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-monthly-weights.sh)
- boatracecsv [`infra/Dockerfile`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/Dockerfile)、[`infra/cloudbuild.yaml`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/cloudbuild.yaml)、[`infra/.dockerignore`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/.dockerignore)
- boatracecsv [`scripts/boatrace/git_operations.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/git_operations.py) — `push()` の fetch + rebase + push

## 演習

自分の GCP プロジェクトで、公開 CSV を 1 日分ダウンロードして集計するだけの Cloud Run Job を作り、Cloud Scheduler から起動してください。GitHub への push も Secret も要らないので、本章の手順から PAT と Cloud Build SA の部分を抜いた最小構成になります。

1. 集計スクリプトを書きます。日付は環境変数 `RUN_DATE` で受け取り、未設定なら JST の前日を使います(Job から `--update-env-vars=RUN_DATE=...` で backfill できる形にしておきます)。

   ```python:summarize_day.py
   import io, os, sys
   from datetime import datetime, timedelta, timezone
   import pandas as pd
   import requests

   BASE = "https://boatracecsv.github.io/data"
   JST = timezone(timedelta(hours=9))

   def target_date() -> str:
       if os.environ.get("RUN_DATE"):
           return os.environ["RUN_DATE"]
       return (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

   def fetch_csv(path: str) -> pd.DataFrame:
       resp = requests.get(f"{BASE}/{path}", timeout=30)
       resp.raise_for_status()
       return pd.read_csv(io.StringIO(resp.text), dtype={"レースコード": str})

   def main() -> int:
       day = target_date()
       results = fetch_csv(f"results/realtime/{day.replace('-', '/')}.csv")
       if results.empty:
           print(f"date={day} races=0 (nothing to do)")
           return 0
       results["1コース1着"] = results["1コース_艇番"] == results["1着_艇番"]
       summary = (results.groupby("レース場")["1コース1着"]
                  .agg(rate="mean", n="size").sort_values("rate", ascending=False))
       print(f"date={day} races={len(results)} stadiums={len(summary)}")
       print(summary.to_string(float_format=lambda v: f"{v:.3f}"))
       return 0

   if __name__ == "__main__":
       sys.exit(main())
   ```

   手元で `RUN_DATE=2026-08-01 python summarize_day.py` と実行すると、`date=2026-08-01 races=156 stadiums=13` に続いて場コード別の 1 コース 1 着率が出ます(この日は 13 場 × 12 レース)。`レース場` 列は場コードなので、名前が欲しければ `programs/title` の同じ日のファイルをレースコードで JOIN してください。

2. Dockerfile を書き、Cloud Build でビルドして Job を deploy します。本章の `cloudbuild.yaml` を使わず `--tag` で直接ビルドするのが手軽です。`--command` の代わりに `CMD` をイメージに焼き込んでも構いません。

   ```dockerfile:Dockerfile
   FROM python:3.11-slim
   ENV PYTHONUNBUFFERED=1 TZ=Asia/Tokyo
   RUN pip install --no-cache-dir pandas requests
   COPY summarize_day.py /app/summarize_day.py
   CMD ["python", "/app/summarize_day.py"]
   ```

   ```bash
   export PROJECT_ID=<your-project-id>
   export REGION=asia-northeast1
   gcloud config set project "$PROJECT_ID"
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
     cloudscheduler.googleapis.com artifactregistry.googleapis.com iam.googleapis.com
   gcloud artifacts repositories create containers \
     --repository-format=docker --location="$REGION"

   IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/containers/summarize-day"
   gcloud builds submit --tag "$IMAGE" .

   gcloud run jobs deploy summarize-day \
     --image="$IMAGE" --region="$REGION" \
     --max-retries=0 --task-timeout=120s --parallelism=1 --tasks=1 \
     --cpu=1 --memory=512Mi

   # 手動実行して stdout を確認する
   gcloud run jobs execute summarize-day --region="$REGION" \
     --update-env-vars=RUN_DATE=2026-08-01 --wait
   gcloud logging read \
     'resource.type="cloud_run_job" AND resource.labels.job_name="summarize-day"' \
     --limit=30 --format='value(textPayload)'
   ```

3. Invoker 用のサービスアカウントを作り、Job の `roles/run.invoker` を付けてから、Cloud Scheduler を JST 23:30(その日の全レースが終わった後)に 1 本登録します。

   ```bash
   gcloud iam service-accounts create summarize-invoker
   INVOKER_EMAIL="summarize-invoker@${PROJECT_ID}.iam.gserviceaccount.com"
   gcloud run jobs add-iam-policy-binding summarize-day --region="$REGION" \
     --member="serviceAccount:${INVOKER_EMAIL}" --role=roles/run.invoker

   gcloud scheduler jobs create http summarize-day-nightly \
     --location="$REGION" \
     --schedule="30 23 * * *" --time-zone="Asia/Tokyo" \
     --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/summarize-day:run" \
     --http-method=POST \
     --oauth-service-account-email="$INVOKER_EMAIL" \
     --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
     --attempt-deadline=60s

   gcloud scheduler jobs run summarize-day-nightly --location="$REGION"
   ```

   Scheduler を即時発火させたあと、手順 2 の `gcloud logging read` で 2 回目の出力が出ていれば完成です。今度は `RUN_DATE` が無いので前日分が集計されるはずです。手順 2 の `execute --update-env-vars` はその実行だけの上書きで Job の定義には残らない、という本章第 5 節の性質を、ここで確かめられます。

4. 発展として、手順 1 のスクリプトを「結果を GCS バケットに CSV で書く」ように変え、実行サービスアカウントを別に作って `roles/storage.objectCreator` をバケットにだけ付けてみてください。Runner と Invoker を分ける本章第 4 節の構成が、そのまま最小権限の練習になります。
