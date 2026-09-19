---
title: "Pub/Sub から静的サイトへ: fun-site のバッチ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 推論結果(CSV)を受け取る側は何を再計算し、何をしないか。強さポイントは再計算せず、買い目・的中・回収率・集計だけを配信側で作る理由。集計期間が伸びても壊れないように、レース 1 件を「集計に要る数項目」へ射影して持つ考え方 |
| システム | GCS ミラーと MD5 dedup、1 実行 1 メッセージの Pub/Sub、Eventarc → Workflows → Cloud Run Job という中継の理由、object generation による早期 return、フルリビルドの判断、OOM を避ける日別ダイジェスト、Cache-Control の手動付与、過去ページを消さない rsync とその事故 |

第 11 章までで、boatracecsv 側の 3 つの Cloud Run Job(`preview-realtime` / `daily-sync` / `monthly-weights`)が CSV を作って GitHub に push するところまでを見ました。
この章は、その CSV を受け取って boatrace-fun.net の静的ページに変える側、fun-site のバッチ(`packages/batch`)の話です。

fun-site には推論パイプラインがありません。データソースは BoatraceCSV の CSV だけで、
「上流が CSV を更新した」というイベントを受けて当日全レースのページを作り直し、GCS に置き、Cloud CDN で配る。それだけをやります。
ただし「それだけ」を JST 08:00〜22:59 のあいだ最短 2 分間隔で繰り返すので、
一回ごとのコストと、一回の失敗の扱いが設計の中心になります。

![上流から配信までのチェーン](/images/boatrace-ml-system/13-realtime-chain.png)
<!-- 図: 左に boatracecsv 側の preview-realtime / daily-sync(Cloud Run Job)。そこから 2 本の矢印: (1) GCS ミラー gs://boatrace-realtime-data-.../data/... へ CSV、(2) Pub/Sub topic fun-site-realtime-completed へ 1 メッセージ。右に fun-site 側: Eventarc trigger → Workflow fun-site-realtime-dispatcher(message.data を containerOverrides.args に載せる)→ Cloud Run Job fun-site-batch。Job の中は縦に 6 段: event-parser / build-state check(早期 return の出口を横に描く)/ fetcher / prediction-builder + aggregator / astro build / deploy + last-build.json。Job から gs://fun-site-web-.../ へ、そこから Cloud CDN → HTTPS LB → 利用者。 -->

## 1. 上流からの通知

### 1.1 GCS ミラーと MD5 dedup

boatracecsv 側の `preview-realtime.py` は、1 サイクルの最後(git push の後)に `boatrace/gcs_publisher.py` を呼びます。
`daily-sync` も `infra/run-daily-sync.sh` の末尾で同じ publisher を 1 回呼ぶので、日次の出走表・強さポイントも直前情報も、同じ経路で fun-site に届きます。

publisher の仕事は 2 つです。1 つ目は、fun-site が当日ビルドで読む CSV を GCS のミラーバケット(`boatrace-realtime-data-{project}`)にアップロードすることです。
対象は日付パーティションを持つ CSV(`programs/title`、`programs/race_cards`、`previews/{stt,tkz,sui,original_exhibition,tokuten_hayami}`、`results/{realtime,payouts}`、`estimate/{predictor_id}`(active 予想者ごと)、`estimate/motor_pt/{runs,motors,baseline}`、`estimate/racer_st`、`estimate/kimarite` など)と、
日付を持たない静的テーブル(`estimate/stadium/win_rate.csv`、`sui_params.csv`、`weights/{predictor_id}/YYYY-MM.csv`)です。
オブジェクト名はリポジトリの相対パスをそのまま使うので、`gs://.../data/programs/title/2026/08/22.csv` のように GitHub Pages の URL と同じ構造になります。
fun-site 側は `CSV_SOURCE=gcs` という環境変数 1 つで取得元を切り替えるだけで、パスの組み立てを変えずに済みます。

アップロードは**内容が変わったときだけ**行います。ローカルファイルの MD5 を計算し、`blob.reload()` で取った GCS 側の `md5_hash` と一致すればスキップします。
これは転送量の節約というより、後述する早期 return のためです。
GCS のオブジェクトは上書きされるたびに `generation`(整数)が進むので、同じ内容を毎サイクル上書きすると generation だけが進み、
下流が「変わっていない」と判定できなくなります。MD5 で dedup することで「内容が同じなら generation も同じ」が成り立ち、下流は stat だけで変化を検出できます。

2 つ目は Pub/Sub への publish です。ここは後述します。
なお GCS と Pub/Sub の失敗は `except Exception` で握って ERROR ログだけ出し、git push の成否には影響させません(第 3 章)。
2 分後に必ず次のサイクルが来るので、1 回の取りこぼしは次で補えるという判断です。

### 1.2 Pub/Sub の payload

publish は **1 実行につき 1 メッセージ**です。レースごとに送ると受け側が同じ日を何度もビルドすることになるので、
そのサイクルで変わったレースの集合を 1 つのメッセージにまとめます。

```json
{
  "publishedAt": "2026-08-22T10:14:03+09:00",
  "raceDate": "2026-08-22",
  "trigger": "realtime",
  "updatedRaces": [
    { "raceCode": "202608220401", "stadiumId": "04", "raceNumber": 1,
      "csvTypes": ["index:v1_basic", "stt"], "indexState": "realtime" },
    { "raceCode": "202608221212", "stadiumId": "12", "raceNumber": 12,
      "csvTypes": ["payouts", "results"] }
  ],
  "gcsPrefix": "gs://boatrace-realtime-data-boatrace-487212/data/"
}
```

(値は形式を示すための例です。)`updatedRaces` は `assemble_updated_races()` が組み立てます。

- アップロード結果に `title` か `race_cards` の変更が含まれていれば、その実行は**日次ブートストラップ**とみなし、`race_cards` に載る全レースを `trigger: "daily-bootstrap"` で送ります(`indexState` は `daily`)
- そうでなければ、今サイクルで直前情報を追記したレース、結果を追記したレース、払戻を追記したレースを、それぞれ独立に集めて `trigger: "realtime"` で送ります。3 つの軸を独立に扱うのは、「結果だけ」「払戻だけ」が更新されたサイクルでも payload が空にならないようにするためです
- `csvTypes` の予想者別 index は `index:{predictor_id}` という形で入ります。fun-site の build-state も同じ命名を使います

`updatedRaces` が空なら publish 自体を行いません(`pubsub_publish_skipped reason=no_updated_races`)。
2 分毎のサイクルの多くは、どのレースも窓に入っておらず何も更新しないので、ここで止まります。

:::message
fun-site 側は `updatedRaces` の中身(どのレースが変わったか)を差分ビルドには使っていません。
使うのは `raceDate` と「空かどうか」だけです。それでもレース単位の情報を載せているのは、
ログから「なぜこのビルドが走ったか」を追えるようにするためと、将来差分ビルドをするときに上流を変えなくて済むようにするためです。
:::

## 2. なぜ Workflow を挟むか

受け側の素直な構成は「Pub/Sub topic → Eventarc trigger → Cloud Run Job」ですが、fun-site はそうなっていません。
Eventarc と Job のあいだに Cloud Workflows を 1 ステップ挟んでいます。

理由は Terraform の制約です。`docs/architecture.md` の記述を引くと、google provider 6.x の `google_eventarc_trigger.destination` は Cloud Run **Service** しか直接指定できず、Cloud Run **Job** は指定できません
(`infra/realtime-pipeline.tf` のコメントでは、destination として書けるのは `cloud_run_service` / `gke` / `workflow` / `http_endpoint` の 4 種とされています)。
Cloud Run Service を立ててそこから Job を起動する構成も考えられますが、Workflow なら destination として直接指定でき、Job を起動する `run.jobs.run` API をそのまま呼べます。

Workflow の本体は Terraform の `source_contents` に書かれた十数行の YAML です。

```yaml
main:
  params: [event]
  steps:
    - extract_message:
        assign:
          - encoded_data: ${event.data.message.data}
    - run_batch_job:
        call: googleapis.run.v2.projects.locations.jobs.run
        args:
          name: projects/${project}/locations/asia-northeast1/jobs/fun-site-batch
          body:
            overrides:
              containerOverrides:
                - args:
                    - ${encoded_data}
        result: execution
    - done:
        return: ${execution}
```

Eventarc から受けた CloudEvent の `event.data.message.data`(Pub/Sub message の data。base64 のまま)を、Cloud Run Job の `containerOverrides.args` に 1 要素として載せます。
`containerOverrides` で上書きできるのは `args` / `env` / `clearArgs` だけで `command`(entrypoint)は変えられないので、
Dockerfile 側を `ENTRYPOINT ["node", "--conditions=production", "dist/main.js"]` + `CMD []` にしておき、args が `process.argv[2]` に来る形に固定しています。

受け側の `event-parser.ts` は、メッセージを次の優先順で探します。

```ts:event-parser.ts(簡略版)
export type ParsedEvent =
  | { readonly kind: "pubsub"; readonly message: RealtimeCompletedMessage }
  | { readonly kind: "none"; readonly reason: string };

export const parseTriggerEvent = (): ParsedEvent => {
  // 1. Workflow が containerOverrides.args で渡す第 1 引数
  const argRaw = process.argv[2];
  if (argRaw) {
    const parsed = tryParseEnvelope(argRaw);
    if (parsed) return { kind: "pubsub", message: parsed };
    console.warn("argv[2] present but failed to parse as Pub/Sub event; falling back");
  }
  // 2. 手動実行や別経路のための環境変数
  const envRaw = process.env["PUBSUB_MESSAGE"] ?? process.env["CE_DATA"];
  if (envRaw) {
    const parsed = tryParseEnvelope(envRaw);
    if (parsed) return { kind: "pubsub", message: parsed };
    console.warn("PUBSUB_MESSAGE/CE_DATA present but failed to parse; falling back");
  }
  // 3. どちらも無ければ当日全レースのフルリビルド
  return { kind: "none", reason: "no event payload" };
};
```

`tryParseEnvelope` は 3 つの形を受け付けます。`{"message": {"data": "<base64>"}}` という Pub/Sub envelope、`raceDate` と `updatedRaces` を直接持つ JSON、そして生の base64 です。
実装コメントにあるとおり「GCP の挙動が時期によって揺れるため両対応する」のが目的で、Workflow 経路では 3 番目(生の base64)が使われます。
どの経路でもパースできなければ `kind: "none"` を返し、当日(JST)の全レースをフルリビルドします。手動の `gcloud run jobs execute` がこの経路です。

サービスアカウントは 3 つに分かれています。

| SA | 役割と権限 |
| --- | --- |
| `fun-site-eventarc@` | Pub/Sub → Workflow の起動。`pubsub.subscriber`、`workflows.invoker`、`eventarc.eventReceiver` |
| `fun-site-workflows@` | Workflow の実行。Job に対する `run.developer`、プロジェクトの `run.viewer`、`logging.logWriter`、batch SA の impersonate |
| `fun-site-batch@` | Job の実行。Web / Data バケットへの書込、CSV ミラーバケットの読取、logging |

`run.viewer` だけプロジェクトレベルなのは、Workflow が `run.jobs.run` の後に operation の完了を `run.operations.get` でポーリングするためで、operation リソースには IAM を絞れないからです(`realtime-pipeline.tf` のコメント)。

この構成は 2026 年 5 月からのものです。初期設計は Cloud Scheduler で JST 09:00 に 1 日 1 回ビルドする朝バッチで、リージョンも `us-central1` でした。
`preview-realtime` が 2 分間隔で CSV を更新するようになったのに合わせて朝バッチを廃止し、イベント駆動に移行し、リージョンを `asia-northeast1` に統一しています。
`infra/cloud-scheduler.tf` が意図的に空ファイルとして残っているのは、`terraform apply` で旧 Scheduler を destroy するための受け皿です。

## 3. パイプライン

### 3.1 処理の順序

`packages/batch/src/pipeline.ts` の `runPipeline()` が全体を並べます。

```
event-parser → build-state check → fetcher → prediction-builder
  → aggregator(digest → predictor-stats / predictor-breakdown)
  → site-builder(JSON 書き出し + GCS 保存 → dates-index → series-aggregator
                 → astro build → deploy → dates-index 書き戻し)
  → last-build.json 保存
```

fetcher は約 20 種の日付 CSV と active 予想者ごとの index CSV を `Promise.all` で並列取得します。
取得は HTTP / GCS のどちらでも指数バックオフで最大 3 回リトライしますが、GCS の 404 だけは即時失敗にします。
404 は「その CSV がまだ書かれていない」状態で、たとえば結果 CSV は最初のレースが確定するまで存在しないので、待っても無駄だからです。
失敗した CSV は warn ログを出して空配列として扱い、`race_cards` が空のときだけパイプラインを止めます。出走表が無ければ作るページが無いからです。

Cloud Run Job のリソースは Terraform の既定値で 2 vCPU / 2Gi、タイムアウト 1800 秒、リトライ 1 回です。
コンテナは multi-stage build で `dist/` を作り込んであります。`tsx` で TypeScript を実行時 JIT すると、コールドスタートに 5〜10 秒余計に積み上がる(Dockerfile のコメント)ためです。
2 分毎に起動されるジョブでは、起動時間そのものが月次コストに直結します。

### 3.2 何を再計算し、何をしないか

ML の観点で押さえておきたいのは、配信側が上流の推論結果をどこまで信用し、どこから先を自分で作るかです。

**再計算しないもの**は強さポイントと各成分の寄与ポイントです。fun-site は `estimate/{predictor_id}` の値をそのまま `AiEvaluation` に写します。
展示ポイントや枠番ポイントを「検算」のために再現するページはありますが(第 16 章)、それは表示用の説明であり、買い目や回収率には使いません。
推論を 2 か所に持つと、レジストリ(第 10 章)の変更を両側で同期する負担が増え、どちらが正かで迷うからです。

**配信側で作るもの**は、強さポイントから先です。1 マーク走行距離を使った三連単フォーメーションの買い目(第 8 章)、`results/realtime` との突き合わせによる的中判定、`results/payouts` を使った払戻と回収率、それらの月次・通算・7 軸の集計(第 17 章)です。
これらは「予想者が何を買ったか」という fun-site 側の意思決定なので、上流には持たせていません。

例外が穴予想の 2 案(`v9_suji` / `v10_kimarite`)で、これだけは買い目そのものを CSV(`estimate/suji`、`estimate/kimarite/picks`)から読みます。
フォーメーションでは表現できない出目集合だからで、`bettingStyleFor(predictorId)` が `"formation"` 以外を返したら CSV 由来の出目を使う、という分岐が `prediction-builder.ts` にあります(第 21 章)。

### 3.3 致命と非致命

パイプラインの各段は「失敗したらどうするか」を明示しています。

| 段 | 失敗時 | 理由 |
| --- | --- | --- |
| build-state check | warn してフルビルドに進む | 早期 return は最適化。ビルドを 1 回余計にやるより、取り逃す方が悪い |
| 個々の CSV 取得 | 空配列で続行(`race_cards` のみ中断) | 直前情報や結果は「まだ無い」のが正常状態 |
| 予想者統計の集計 | warn して続行 | `/predictors` と `/stats` が空になるだけでレースページは出せる |
| 節集計、GCS への JSON 保存、dates.json 書き戻し | warn して続行 | 次回ビルドで追従できる |
| Astro build、deploy | 例外で Job 失敗 | ここが失敗したら配るものが無い。Cloud Run のリトライと次サイクルに任せる |

`last-build.json` の保存は deploy の**後**にあります。deploy が失敗した回は記録が更新されないので、次のサイクルで自然に再ビルドされます。

## 4. 早期 return

2 分毎に起動されるジョブで、コストの肝は「何も変わっていないときにどれだけ早く終われるか」です。fun-site は 2 段で判定します。

### 4.1 2 段の判定

```ts:pipeline.ts(冒頭の簡略版)
export const runPipeline = async (): Promise<void> => {
  const event = parseTriggerEvent();
  const raceDate = event.kind === "pubsub" ? event.message.raceDate : toJSTDateString(new Date());

  // Step 0a: updatedRaces が空なら何も変わっていない(preview-realtime の空回り)
  if (event.kind === "pubsub" && event.message.updatedRaces.length === 0) {
    console.info("Skipping build: updatedRaces is empty");
    return;
  }

  // Step 0b: GCS の generation が前回ビルドと全部同じなら終了
  if (process.env["CSV_SOURCE"] === "gcs" && process.env["FORCE_REBUILD"] !== "1") {
    const [previous, current] = await Promise.all([
      loadBuildState(),
      fetchCurrentCsvGenerations(raceDate),
    ]);
    if (isUpToDate(raceDate, current, previous)) {
      console.info(`Skipping build: CSV generations unchanged since last build at ${previous?.lastBuildAt}`);
      return;
    }
  }
  // Step 1 以降: fetch → build → aggregate → astro build → deploy → saveBuildState
};
```

Step 0a は上流の publisher が空なら送らないので、通常は通りません。手で送ったメッセージや、将来 publisher の判定が変わったときのための二重の防御です。

Step 0b が本体です。前回ビルド時に記録した各 CSV の GCS object generation(`_meta/last-build.json`)と、今の generation を比較します。
比較に使うのは `getMetadata()` だけで、CSV 本文はダウンロードしません。数十オブジェクトの stat を並列に投げるだけなので、ここで終われば CSV の取得も Astro ビルドも走らず、ごく短時間で済みます。

### 4.2 build-state の実装

```ts:build-state.ts(簡略版)
import { activePredictors } from "@fun-site/shared";
import { Storage } from "@google-cloud/storage";

/** 実装は 20 種。本質だけ残す */
type CsvType = "title" | "race_cards" | "stt" | "results" | "payouts";
export type CsvGenerationKey = CsvType | `index:${string}` | "waku_table" | "sui_params";

export type BuildState = {
  readonly lastBuildAt: string;
  readonly raceDate: string;
  /** ビルド時に参照した GCS object の generation。キー → generation 文字列 */
  readonly csvGenerations: Partial<Record<CsvGenerationKey, string>>;
};

const CSV_PATH_PREFIX: Record<CsvType, string> = {
  title: "programs/title",
  race_cards: "programs/race_cards",
  stt: "previews/stt",
  results: "results/realtime",
  payouts: "results/payouts",
};

const storage = new Storage();
const WEB_BUCKET = process.env["GCS_WEB_BUCKET"] ?? "fun-site-web-boatrace-487212";
const CSV_GCS_BUCKET = process.env["CSV_GCS_BUCKET"] ?? "boatrace-realtime-data";
const META_OBJECT_NAME = "_meta/last-build.json";

/** 監視対象 = 日付 CSV + active 予想者ごとの index + 日付を持たない静的テーブル */
const buildTrackedKeys = (date: string): { key: CsvGenerationKey; objectName: string }[] => {
  const dateSlash = date.replaceAll("-", "/");
  const keys: { key: CsvGenerationKey; objectName: string }[] = (
    Object.keys(CSV_PATH_PREFIX) as CsvType[]
  ).map((type) => ({ key: type, objectName: `data/${CSV_PATH_PREFIX[type]}/${dateSlash}.csv` }));
  for (const p of activePredictors()) {
    keys.push({ key: `index:${p.id}`, objectName: `data/estimate/${p.id}/${dateSlash}.csv` });
  }
  keys.push({ key: "waku_table", objectName: "data/estimate/stadium/win_rate.csv" });
  keys.push({ key: "sui_params", objectName: "data/estimate/stadium/sui_params.csv" });
  return keys;
};

/** 前回ビルドの記録。未存在・破損は「前回なし」として扱う */
export const loadBuildState = async (): Promise<BuildState | undefined> => {
  try {
    const [buf] = await storage.bucket(WEB_BUCKET).file(META_OBJECT_NAME).download();
    return JSON.parse(buf.toString("utf-8")) as BuildState;
  } catch {
    return undefined;
  }
};

/** 当日 CSV 群の generation を stat で一括取得(本文は読まない)。不在は undefined */
export const fetchCurrentCsvGenerations = async (
  date: string,
): Promise<Partial<Record<CsvGenerationKey, string>>> => {
  const bucket = storage.bucket(CSV_GCS_BUCKET);
  const result: Partial<Record<CsvGenerationKey, string>> = {};
  await Promise.all(
    buildTrackedKeys(date).map(async ({ key, objectName }) => {
      try {
        const [meta] = await bucket.file(objectName).getMetadata();
        if (meta.generation) result[key] = String(meta.generation);
      } catch {
        // 404 = まだ書かれていない CSV。undefined のままにする
      }
    }),
  );
  return result;
};

/** 同一 raceDate かつ全キーの generation が一致 → true(早期 return 可能) */
export const isUpToDate = (
  date: string,
  current: Partial<Record<CsvGenerationKey, string>>,
  previous: BuildState | undefined,
): boolean => {
  if (!previous || previous.raceDate !== date) return false;
  for (const { key } of buildTrackedKeys(date)) {
    const cur = current[key];
    const prev = previous.csvGenerations[key];
    if (cur === undefined && prev === undefined) continue; // 両方未存在なら比較しない
    if (cur !== prev) return false;
  }
  return true;
};
```

設計上の要点を 4 つ挙げます。

- **監視対象にはレジストリの active 予想者ぶんの index が動的に入る**。予想者を追加・退役すると、上流の publisher も fun-site の build-state も `activePredictors()` から同じキー(`index:{predictor_id}`)を生成するので、両側で同期漏れが起きません
- **日付を持たない静的テーブルも監視する**。`win_rate.csv` と `sui_params.csv` は月 1 回しか変わりませんが、変わると全レースの枠番ポイント・気象ポイントの解説ページ(第 16 章)が変わるので、日付 CSV が変わらなくてもビルドが要ります。一方 `weights/{predictor_id}/YYYY-MM.csv` は月ごとにパスが変わり「対象月以下で最新」を stat だけでは解決できないため対象外です。weights だけが変わって `win_rate.csv` が据え置きというケースは起きえますが、その場合も次の日次 CSV 更新でビルドが走ります
- **両方 undefined は「変化なし」**。当日まだ書かれていない CSV(朝の `results` など)を、前回も今回も無いなら比較から外します。これを「不一致」にすると、結果 CSV ができるまで毎サイクルフルビルドになります
- **`raceDate` が違えば無条件にビルド**。日付が変わった最初のメッセージは、前日の記録と比較する意味がありません

`last-build.json` は Web バケットの `_meta/` に `Cache-Control: no-store` で置きます。deploy の削除フィルタが `_meta/` を守っている(6.2 節)のは、このファイルを消さないためでもあります。

### 4.3 なぜ差分ビルドをしないか

`updatedRaces` にはレース単位の差分が入ってくるので、変わったレースのページだけ作り直す差分ビルドを考えたくなります。fun-site はそれをせず、毎回当日ぶんをフルリビルドします。

理由は Astro SSG の依存関係が当日分に広く及ぶからです。トップページは開催中の全場の「次のレース」を並べ、会場ページは 1〜12R を並べ、レース詳細ページの 1R〜12R リンクバーは各レースの的中状況を持ち、`/predictors/` と `/stats/` は全レースの集計です。
1 レースの結果が確定すると、そのレースのページだけでなくトップ・会場・集計ページが変わります。どのページが影響を受けるかをレースごとに追跡する仕組みを作るより、
「当日 1 日ぶん(数百ページ)を全部作る」方が単純で、壊れにくい。ビルド時間はページ数に比例するので、対象を当日 1 日ぶんに絞ることで上限を抑えています(Job のタイムアウトは 1800 秒)。

代わりに deploy 側で差分を取ります(6.2 節)。生成した全ファイルの MD5 を GCS 側と比べ、変わったものだけをアップロードするので、「フルビルド・差分デプロイ」という組み合わせになります。

### 4.4 強制再ビルド

`FORCE_REBUILD=1` で Step 0b を無効化できます。運用では Job の環境変数を一時的に上書きして実行し、終わったら戻します。

```bash
gcloud run jobs execute fun-site-batch --region=asia-northeast1 \
  --update-env-vars FORCE_REBUILD=1 --wait
gcloud run jobs update fun-site-batch --region=asia-northeast1 \
  --remove-env-vars FORCE_REBUILD
```

戻し忘れると以後のすべてのサイクルがフルビルドになるので、`--update-env-vars` と `--remove-env-vars` は必ず対で使います。
過去日の再生成も同じ要領で、`BUILD_TARGET_DATE=YYYY-MM-DD` を加えます。

## 5. OOM を避ける射影

### 5.1 何が起きたか

`/predictors/`(予想者比較)と `/stats/`(7 軸のブレークダウン)は、active 予想者の `startedAt` から当日までの全レースを集計します(第 17 章)。
予想者が数か月運用されると、集計期間も数か月分になります。

レース 1 件の `RacePrediction` JSON は、選手成績・近況 5 節・枠番別過去 10 走・モーターポイントの素点内訳などを抱えて 1 件 100KB を超えます
(2026-08-23 にモーターポイントの内訳を載せたとき、整形済み JSON は 74KB → 183KB に太りました)。
これを数か月分メモリに載せると、Node のヒープ上限(2Gi コンテナで約 1GB)を超えて OOM でクラッシュします。
統計集計は try/catch で非致命扱いにしてありますが、OOM はプロセスごと落ちるので例外として捕まえられず、Job 全体が失敗してレースページの更新も止まります。
運用を始めた直後には現れず、予想者の運用期間が伸びるにつれて静かに近づいてくる種類の障害です。

### 5.2 集計に要る項目だけを持つ

2026-09-15 の修正で、集計器には `RacePrediction` を渡さず、集計に必要な項目だけを抜いた `PredictionDigest` を渡す形に変えました。

```ts:aggregator/prediction-digest.ts(簡略版)
export type PredictorDigest = {
  readonly predictorId: string;
  readonly betCount: number;      // 直前買い目の点数
  readonly betCostYen: number;    // 直前買い目の購入額。0 なら買い目が組めていない
  readonly payoutYen: number;     // 直前買い目の払戻額
  readonly dailyHit: boolean;
  readonly realtimeHit: boolean;
  readonly honmeiWaku?: number;   // 直前 AI 評価の強さpt 最大艇の枠番
  readonly sanrentanPayout?: number; // 確定 3連単 配当
};

export type PredictionDigest = {
  readonly raceCode: string;
  readonly raceDate: string;
  readonly stadiumId: string;
  readonly grade: string;
  readonly settled: boolean;      // false のレースは集計母数に入らない
  readonly windSpeed?: number;
  readonly predictors: readonly PredictorDigest[];
};

/** ダイジェストの形を変えたら上げる。GCS キャッシュの読み込み時に不一致なら作り直す */
export const PREDICTION_DIGEST_SCHEMA_VERSION = 1 as const;

const honmeiWakuOf = (evaluation: AiEvaluation | undefined): number | undefined => {
  let best: AiEvaluationEntry | undefined;
  for (const e of evaluation?.entries ?? []) {
    if (!best || e.strengthPt > best.strengthPt) best = e;
  }
  return best?.boatNumber;
};

/** RacePrediction 1 件(100KB 超)を数百バイトに畳む。射影の唯一の入口 */
export const toPredictionDigest = (pred: RacePrediction): PredictionDigest => {
  const predictors = (pred.predictions ?? []).map((pp): PredictorDigest => {
    const realtime = pp.betPayout.realtime;
    const honmeiWaku = honmeiWakuOf(pp.aiEvaluationRealtime);
    const sanrentanPayout = realtime.actualSanrentan?.payout;
    return {
      predictorId: pp.predictorId,
      betCount: realtime.betCount,
      betCostYen: realtime.betCostYen,
      payoutYen: realtime.payoutYen,
      dailyHit: pp.betHitStatus.dailyHit,
      realtimeHit: pp.betHitStatus.realtimeHit,
      ...(honmeiWaku === undefined ? {} : { honmeiWaku }),
      ...(sanrentanPayout === undefined ? {} : { sanrentanPayout }),
    };
  });
  const windSpeed = pred.raceResult?.weather.windSpeed;
  return {
    raceCode: pred.raceCode,
    raceDate: pred.raceDate,
    stadiumId: pred.stadiumId,
    grade: pred.grade ?? "",
    settled: isSettledResult(pred.raceResult),
    ...(windSpeed === undefined ? {} : { windSpeed }),
    predictors,
  };
};
```

7 軸の集計(場別・グレード別・買い目点数別・本命枠番別・配当帯別・風速別・時系列)に要る項目は、この型に閉じています。
`honmeiWaku` のように「元データから導出する値」もダイジェスト生成時に確定させ、集計器はそれ以上元データに触れません。
`toPredictionDigest` を射影の唯一の入口にしているのは、集計軸を足すときに「ダイジェストに項目を足す → スキーマバージョンを上げる」という 1 本の手順に収めるためです。

### 5.3 日別キャッシュと並列度

射影だけでは、過去日の `RacePrediction` JSON を毎ビルド読み直すコストが残ります。そこで `prediction-digest-store.ts` が日別にキャッシュします。

- **当日(raceDate)** はメモリ上の `RacePrediction[]` から毎回作り直し、`gs://${GCS_DATA_BUCKET}/_meta/prediction-digests/{date}.json` に上書き保存する。当日は結果が順次確定して値が変わるため
- **過去日**はまずキャッシュを読む。無い、または `schemaVersion` が違うときだけ、`predictions/{date}/*.json` を 1 件ずつ射影しながら読んで保存する。確定後の過去日は変わらないので、以後は再計算しない
- **元データが空の日は保存しない**。一覧取得の一時的な失敗を「レース無し」として固定してしまうのを避けるため
- 過去日は**最大 4 日並列、日の中では 16 並列**で読む。日単位で読んで畳んで捨てるので、期間が伸びてもメモリはほぼ一定。ダイジェストは数か月分でも数 MB に収まる

運用上の操作は 2 つだけです。ある日だけ作り直したければ GCS の該当ファイルを消す。全日を作り直したければ `PREDICTION_DIGEST_SCHEMA_VERSION` を上げる。
キャッシュが無い初回のビルドは全期間の JSON を読むので数分かかりますが、メモリは日単位で解放されるので期間の長さで OOM にはなりません。

:::message
集計に何が要るかを型として書き出し、元データを丸ごと持たないことは、期間に依存しない設計の基本形です。
「今は数日分しかない」段階で、数か月後の入力サイズを想定してデータの持ち方を決めておくと、後から作り直さずに済みます。
:::

## 6. デプロイの落とし穴

### 6.1 Cache-Control は自分で付ける

配信は GCS の Web バケットを backend bucket にした HTTPS ロードバランサ + Cloud CDN です。
CDN のキャッシュモードは `CACHE_ALL_STATIC` で、`default_ttl` は `cdn_cache_ttl` 変数(既定 3600 秒)、`max_ttl` はその 24 倍、`serve_while_stale` は 86400 秒です。

この設定では、オブジェクトに `Cache-Control` が無いと HTML まで最大 1 時間(stale 配信なら最大 1 日)キャッシュされます。
2 分毎に再ビルドしても、利用者には古いトップページが配信され続けることになります。2026-05-30 に、`deploy.ts` がアップロード時に種別ごとの `Cache-Control` を付けるようにしました。

```ts:site-builder/deploy.ts(Cache-Control)
const getCacheControl = (destination: string): string => {
  if (destination.endsWith(".html")) return "no-cache";
  if (destination.startsWith("_astro/")) return "public, max-age=31536000, immutable";
  return "public, max-age=3600";
};
```

- `.html` は `no-cache`。キャッシュはするが、使う前に必ずオリジンへ再検証する。HTML は毎ビルド変わりうるので常に最新を出す
- `_astro/` 配下は 1 年 + `immutable`。Astro が content-hash で命名する CSS / JS で、内容が変わればファイル名も変わるので、同じ URL の内容が変わることはない
- それ以外(favicon、robots、sitemap など)は 1 時間

注意点が 1 つあります。deploy は MD5 が一致するファイルのアップロードをスキップするので、内容が変わらないオブジェクトには新しい `Cache-Control` が反映されません。
HTML は再ビルドごとに内容が変わるため次のサイクルで自動的に新しいヘッダに更新されますが、ヘッダの方針を変えたときに静的ファイルへ即時に効かせたいなら、別途対応が要ります。

### 6.2 過去日を消さない rsync

deploy は `rsync -d` 相当の動きをします。ローカルの `web/dist/` を再帰的に列挙し、MD5 を 16 並列で計算して GCS 側の `md5Hash` と比べ、変わったものだけを 16 並列でアップロードします
(この差分化の前は、毎回約 330 ページを全部アップロードしていました)。その後、ローカルに無いリモートのオブジェクトを削除します。

ここに罠があります。バッチが作るのは**当日 1 日ぶん**だけなので、過去日の `race/{date}/...` と `archive/{date}/` はローカルに存在しません。
素朴に「ローカルに無いものを消す」と、過去日のページが GCS から全部消えます。過去日のページは既にデプロイ済みでそのまま公開できるので、削除対象から外します。

```ts:site-builder/deploy.ts(削除フィルタ)
/** ローカルに無いリモートを消す(rsync -d 相当)。ただし守るものがある */
const selectStaleObjects = (remoteNames: readonly string[], uploadedNames: ReadonlySet<string>): string[] => {
  const todayJST = process.env["BUILD_TARGET_DATE"] ?? toJSTDateString(new Date());
  const DATE_PREFIX_RE = /^(race|archive)\/(\d{4}-\d{2}-\d{2})\//;
  return remoteNames.filter((name) => {
    if (uploadedNames.has(name)) return false;
    // images/ は別工程の成果物、_meta/ は last-build.json 等、_astro/ は過去ページが参照する CSS/JS
    if (name.startsWith("images/") || name.startsWith("_meta/") || name.startsWith("_astro/")) {
      return false;
    }
    // 当日以外の race/ archive/ はローカルに存在しないが、公開を続ける
    const m = name.match(DATE_PREFIX_RE);
    if (m && m[2] !== todayJST) return false;
    return true;
  });
};
```

守っているのは 4 種類です。`images/` は別工程の成果物、`_meta/` は `last-build.json` や `dates.json`、`_astro/` は content-hash 付きの CSS / JS、そして当日以外の日付ディレクトリです。

### 6.3 CSS ハッシュの事故と復旧

このフィルタのうち `_astro/` は、最初からあったわけではありません。

過去日の HTML を残すようにした後も、旧 `deploy.ts` は `_astro/` 配下を毎ビルド削除していました。当日ぶんの HTML が参照する CSS はその回のビルドで生成されるので、当日だけ見ていれば問題はありません。
しかし過去日の HTML は、**生成された当時の**ハッシュ名の CSS(`/_astro/_date_.Dyh1rilZ.css` のような名前)を参照しています。
CSS の内容が少しでも変わればハッシュが変わり、古いハッシュのファイルは削除され、過去日のページはスタイルの無い状態で表示されるようになります。HTML は 200 で返り、CSS だけが 404 になる、気づきにくい壊れ方です。

2026-05-19 に 2 つの対応を入れました。1 つは削除フィルタに `_astro/` を加えて将来の削除を止めることです。content-hash 命名なので同名上書きは起きず、蓄積しても破綻しません(必要なら別途まとめて掃除します)。
もう 1 つは、既に壊れた過去 HTML を書き換えるワンショットスクリプト `scripts/recover-past-css.ts` です。

```bash
DRY_RUN=1 pnpm --filter @fun-site/batch run recover-past-css   # 変更予定だけ表示
pnpm --filter @fun-site/batch run recover-past-css             # 本番適用
```

スクリプトは GCS 上の `_astro/*.css` を列挙して有効なパスの集合を作り、過去日の `race/<date>/.../*.html` と `archive/<date>/*.html` を全部読んで、
`<link rel="stylesheet" href="/_astro/*.css">` のうちリンク先が現存しないものだけを現行の CSS に置き換えて保存します。有効なリンクは触りません。
置換先は通常 1 つ(グローバル CSS が 1 ファイル)で、複数あればサイズ最大のものを使います。
書き換え後も CDN のキャッシュに古い 404 が残ることがあるので、必要に応じてキャッシュ無効化を併用します。

:::message alert
「消してよいもの」の判断は、当日のビルドだけを見ていると誤ります。
GCS に残置している過去ページが何を参照しているかまで含めて、削除フィルタを設計する必要があります。
`_astro/` のように「今回のビルドで作ったものと同じ場所に、過去のビルドの成果物が同居する」ディレクトリが特に危険です。
:::

### 6.4 dates.json の書き戻し順

`/archive/` の日付一覧は `gs://${GCS_WEB_BUCKET}/_meta/dates.json` を情報源にします。`buildAndDeploy()` は開始時にこれを取得して当日をマージし、ローカルに書き出して Astro に読ませ、
**deploy が成功した後で** GCS に書き戻します。deploy 前に書き戻すと、ビルドが失敗した日が一覧に載ってしまうからです。
機能導入時に既存の過去ページを取り込むための `seed-archive-dates` スクリプトも同じ理由で `DRY_RUN=1` を持ちます。

## 7. Terraform の構成

インフラは `infra/` の Terraform で管理します(provider google / google-beta ~6.0、state は GCS backend)。ファイル別の責務は次のとおりです。

| ファイル | 主なリソース |
| --- | --- |
| `infra/main.tf` | provider 設定、必須 API の有効化 |
| `infra/variables.tf` | 入力変数の宣言 |
| `infra/outputs.tf` | バケット名・URL・Job 名・LB IP などの出力 |
| `infra/artifact-registry.tf` | Docker レジストリ(batch コンテナ用、最新 10 世代 + 30 日保持) |
| `infra/cloud-build.tf` | main ブランチ push トリガー |
| `infra/cloud-run-jobs.tf` | `fun-site-batch` Cloud Run Job |
| `infra/cloud-scheduler.tf` | 空(旧朝バッチ廃止後、destroy 対象の受け皿) |
| `infra/cloud-storage.tf` | Web / Data バケット |
| `infra/dns.tf` | Cloud DNS ゾーン + A レコード |
| `infra/iam.tf` | batch SA、Cloud Build SA |
| `infra/monitoring.tf` | 通知チャネル、アラートポリシー、ログメトリクス、ダッシュボード |
| `infra/networking.tf` | グローバル IP、backend bucket、CDN、URL Map、証明書、LB |
| `infra/realtime-pipeline.tf` | Pub/Sub topic、CSV ミラーバケット、Workflow、Eventarc trigger、各種 IAM |

バケットは 3 つで、役割ごとにライフサイクルが違います。

| バケット | 用途 | ライフサイクル | 公開 |
| --- | --- | --- | --- |
| `fun-site-web-{project}` | 静的サイト配信 | なし | 公開読取(CDN 経由) |
| `fun-site-data-{project}` | `last-build.json`、予想 JSON、ダイジェスト、中間ファイル | 90 日超 → NEARLINE、バージョン管理あり | 非公開 |
| `boatrace-realtime-data-{project}` | preview-realtime が書く CSV ミラー | 30 日超 → NEARLINE、365 日超 → COLDLINE | 非公開 |

CSV ミラーは当日ぶんだけがホットパスなので、30 日で NEARLINE に落とします。過去日を再ビルドするときに NEARLINE / COLDLINE から読むことは可能で、コストが上がるだけです。
Pub/Sub topic の保持は 1 日(`86400s`)です。Eventarc が即時に消費する想定で、溜め込む用途ではありません。

監視は `monitoring.tf` で、Cloud Run Job の ERROR ログを検出してメール通知(1 時間ごとに最大 1 通)、batch 実行時間のログメトリクス、Job 実行数・CDN リクエスト数・キャッシュヒット率・ストレージ容量のダッシュボードを持ちます。
CI/CD は main ブランチへの push で Cloud Build が `install → lint / typecheck / test(並列)→ docker-build → docker-push → Cloud Run Job のイメージ更新` を実行します。

## 8. 動作確認とトラブルシューティング

チェーンが長いので、動かないときはどこで止まっているかを順に切り分けます。`docs/operations.md` の手順を要約します。

1. `gcloud run jobs execute preview-realtime --wait` で上流を手動実行し、ログに `gcs_upload_success` と `pubsub_publish_success` が出るか
2. `gsutil ls` でミラーバケットに当日の CSV があるか
3. `gcloud workflows executions list --workflow=fun-site-realtime-dispatcher` で Workflow が起動し `SUCCEEDED` か。続いて `gcloud beta run jobs executions list --job=fun-site-batch`
4. 2 サイクル連続で実行し、2 回目のログが `Skipping build: CSV generations unchanged` で終わるか
5. 公開サイトの当日レースページが更新されているか

| 症状 | 確認ポイント |
| --- | --- |
| サイトが更新されない | Workflow の executions、Job の executions、`Skipping build` ログの有無 |
| 直前情報が反映されない | ミラーバケットに最新の `previews/stt` が届いているか、index CSV の `状態` が `realtime` になっているか |
| ビルドが空振りで終わる | `last-build.json` の generation を確認。`FORCE_REBUILD=1` で再実行 |
| LB 経由で 502 / 504 | backend bucket の設定、Web バケットの `allUsers` への `objectViewer`、CDN キャッシュ |

チェーンを止めたいときは Eventarc trigger を削除します(Pub/Sub にメッセージは溜まるが Workflow が起動しない)。復旧は `terraform apply` で作り直します。
Pub/Sub チェーンが長く回復しない場合の繋ぎとして、Cloud Scheduler を手動で作って 1 日 1 回 Job を叩く朝バッチの手順も残してありますが、通常運用では使いません。

## 元資料

- https://github.com/BoatraceCSV/fun-site/blob/main/docs/architecture.md — 全体構成、なぜ Workflow を挟むか、データフローの粒度、経緯
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/batch.md — パイプラインの各段、prediction-digest、環境変数
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/infrastructure.md — Terraform のファイル別責務、SA、バケット、CDN と Cache-Control
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/operations.md — 動作確認、強制再ビルド、過去ページの CSS 復旧、トラブルシューティング
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/data-sources.md — GCS ミラー、リトライと generation、CSV のライフサイクル
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/pipeline.ts — オーケストレーションと早期 return の 2 段判定
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/build-state.ts — generation の記録と比較
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/event-parser.ts — メッセージの復元(argv → 環境変数)
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/fetcher/csv-client.ts — HTTP / GCS の切り替え、リトライ、weights の月次遡り
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/prediction-digest.ts — 射影
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/prediction-digest-store.ts — 日別キャッシュと並列度
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/site-builder/deploy.ts — Cache-Control と削除フィルタ
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/scripts/recover-past-css.ts — 過去 HTML の CSS 参照復旧
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/Dockerfile — ENTRYPOINT / CMD の分け方
- https://github.com/BoatraceCSV/fun-site/blob/main/infra/realtime-pipeline.tf — Pub/Sub、Workflow、Eventarc、IAM
- https://github.com/BoatraceCSV/fun-site/blob/main/infra/cloud-run-jobs.tf — Job の定義と環境変数
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/gcs_publisher.py — MD5 dedup、updatedRaces の組み立て、Pub/Sub payload

## 演習

公開 CSV だけで解けます。2026-08-22(13 場開催、156 レース)の直前情報と結果を使います。

- `https://boatracecsv.github.io/data/previews/stt/2026/08/22.csv`
- `https://boatracecsv.github.io/data/results/realtime/2026/08/22.csv`

どちらも `取得日時` 列に、その行を追記したサイクルの時刻が JST で入っています。
これを 2 分単位に丸めると、「そのサイクルで preview-realtime が何レース分を更新したか」、つまり Pub/Sub メッセージの `updatedRaces` の長さを復元できます。

```python:ex_cycles.py
import pandas as pd

BASE = "https://boatracecsv.github.io/data"
DATE = "2026/08/22"

def cycles(kind: str) -> pd.Series:
    df = pd.read_csv(f"{BASE}/{kind}/{DATE}.csv", dtype={"レースコード": str})
    t = pd.to_datetime(df["取得日時"]).dt.floor("2min")
    return t.value_counts().sort_index()

stt = cycles("previews/stt")
res = cycles("results/realtime")
print("stt: rows", stt.sum(), "cycles", len(stt), "races/cycle mean %.2f max %d" % (stt.mean(), stt.max()))
print("results: rows", res.sum(), "cycles", len(res), "races/cycle mean %.2f max %d" % (res.mean(), res.max()))
both = pd.concat([stt.rename("stt"), res.rename("results")], axis=1, sort=True).fillna(0).astype(int)
print("cycles with any update:", len(both), "of", (both.index.max() - both.index.min()) / pd.Timedelta("2min") + 1)
print("cycles with results only:", int(((both["stt"] == 0) & (both["results"] > 0)).sum()))
```

1. 上のスクリプトを動かし、`stt` と `results` それぞれで「1 サイクルあたり何レース更新されたか」の平均と最大を求めてください。1 サイクル 1 レース前後に収まるはずです(2026-08-22 の実測は stt 152 サイクル / 平均 1.03 / 最大 2、results 132 サイクル / 平均 1.18 / 最大 3)。締切時刻が場ごとにずれていることの帰結です
2. 最初の更新から最後の更新までの 2 分サイクル数と、実際に何かを更新したサイクル数を比べてください(同日の実測は 437 サイクル中 216)。差分が、上流の publisher が `no_updated_races` で publish をスキップするサイクル、つまり fun-site の Job が起動すらしない回数の下限です
3. `stt` の更新が無く `results` だけが更新されたサイクルを数えてください(同日の実測は 64 サイクル)。`assemble_updated_races()` が preview / results / payouts の 3 軸を独立に扱わなければ、これらのサイクルは payload が空になって配信に反映されなかったはずです
4. (発展)上の payload 例(1.2 節)を手で JSON にし、base64 エンコードしてから、Python で `{"message": {"data": "<base64>"}}` の envelope に包んで、`event-parser.ts` が受け付ける 3 つの形(envelope / 素の JSON / 生の base64)をそれぞれ復元してみてください。fun-site をローカルに clone していれば、`pnpm --filter @fun-site/batch run start '{"publishedAt":"","raceDate":"2026-08-22","updatedRaces":[]}'` のように渡すと、GCP の認証なしで `Skipping build: updatedRaces is empty` を確認できます
