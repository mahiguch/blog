---
title: "的中率・回収率ダッシュボード"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 集計軸ごとに回収率を割ると何が分かり、何が分からないか。n が小さいセルを信じない仕組みを画面側に持つ。回収率だけでは測れない「体験」を指標にする |
| システム | 集計をバッチで前計算して静的 JSON にする、1 レース 100KB 超の予想を数百バイトのダイジェストに射影して日別にキャッシュする、予想者ごとに違う母数を扱う、集計失敗を非致命にする |

第 9 章で「何を指標にするか」と「母数をどう定義するか」を決め、第 10 章で予想者を投入・退役させるレジストリを作りました。この章はそれを **毎日の画面** にする話です。boatrace-fun.net には予想者を比べる `/predictors/` と、直前買い目の成績を 7 軸に割る `/stats/` の 2 ページがあり、どちらも fun-site のバッチが書き出した JSON を Astro が読むだけで動きます。集計器の実装は 2 ファイル(`predictor-stats.ts` と `predictor-breakdown.ts`)で、この章の後半で本質だけを 60 行に切り出します。

![統計ページ](/images/boatrace-ml-system/17-stats-page.png)
<!-- 図: boatrace-fun.net の /stats/ ページのスクリーンショット。上から「直前通算」の表(予想者 / レース数 / 的中率 / 回収率)、累積回収率の折れ線(破線 = 100%)、その下に「本命予想 — 分析軸別」として 場別 / グレード別 / 買い目点数別 / 本命枠番別 / 配当帯別 / 風速別 の 6 表が 2 列グリッドで並ぶ。n < 20 の行が灰色で「参考」バッジ付きになっている箇所が写るように切り出す。(2026-09-19 撮影: 本命予想には n < 20 のセルが無いため「参考」行は写っていない。参考行が必要ならスジ予想の節を撮る) -->

## 1. 予想者別の成績ページ

### 通算と月次

`/predictors/` は `packages/web/src/data/predictors/stats.json` を読み、active・retired を含む全予想者について次を表にします。

| 列 | 中身 |
| --- | --- |
| レース数 | 集計対象になったレース数(母数) |
| 的中率 | 直前買い目が的中したレース数 ÷ 母数 |
| 購入額 | 直前買い目の点数 × 100 円の合計 |
| 払戻 | 的中レースの 3 連単払戻金の合計 |
| 回収率 | 払戻 ÷ 購入額 |

同じ列を月(`YYYY-MM`)ごとに切った表が予想者ごとに続き、月次推移を追えるようになっています。active な予想者が先頭で slot 昇順、retired はその後ろに灰色で並びます。退役した予想者を消さないのは、第 10 章で見たとおり「累計回収率の同一性」を保つためで、レジストリの ID を再利用しないルールと対になっています。

### 母数は「確定済みかつ直前買い目が組めたレース」

集計対象は第 9 章で決めた定義をそのまま使います。

- `isSettledResult(raceResult)`: 1〜3 着が相異なる艇番で揃っている
- `betPayout.realtime.betCostYen > 0`: 直前買い目が組めている

結果未着(当日進行中)・中止・不成立・返還のレースは、的中数と払戻(分子)からも、母数と購入額(分母)からも外します。当日進行中のレースを分母に入れると、夕方まで的中率が「水増しの逆」で低く出てしまうので、分子と分母の対象を必ず揃えます。

指標は **直前(realtime)買い目だけ** です。当日(daily)買い目の的中数は `dailyHitCount` として参考値で残しますが、的中率にも回収率にも使いません。理由は、`/stats/` と会場ページの「今節成績」がどちらも直前買い目で集計しており、ページによって数字が食い違うと説明できなくなるためです。

### 「もし買ったら」の想定

回収率は「買い目フォーメーションの全組合せを 1 点 100 円の 3 連単として買った」想定です。実際に舟券を買っているわけではなく、レース詳細ページの予想者カードにはそのレース単位の購入額・払戻(`BetPayoutSummary`)が出ます。この 1 レースぶんの値を、予想者 × 期間で足し上げたものが成績ページです。

### 予想者ごとに母数が違う

予想者には `startedAt` があり、集計期間は `datesForActivePredictors(raceDate)` が「active な予想者のうち最古の `startedAt`」から当日までの日付配列として作ります。2026 年 8 月時点の active は `v1_basic`(2026-05-01 開始)と `v10_kimarite`(2026-08-13 開始)なので、集計期間は 5 月 1 日から当日までになりますが、`v10_kimarite` の行に入るのは 8 月 13 日以降のレースだけです。会場ページの今節成績でも、その節に集計対象が無い予想者は `—` になります。予想者を並べて見るときは、レース数の列が違うことを常に意識する必要があります。

## 2. 7 軸のブレークダウン

`/stats/` は `breakdown.json` を読み、各予想者の直前買い目を **時系列 + 6 軸** に割ります。すべてのセルが `Metrics` 型(`raceCount` / `hitCount` / `hitRate` / `betCostYen` / `payoutYen` / `recoveryRate`)で、`hitRate` と `recoveryRate` は分母が 0 のとき `null` です。

### 各軸で何が分かるか

| 軸 | 区分の取り方 | 見えること |
| --- | --- | --- |
| 時系列 | 日次の単独値と、`startedAt` からの累積 | 累積回収率が 100% の破線を挟んでどう落ち着いていくか。開始直後は大きく揺れ、n が増えるにつれ収束する様子がそのまま「回収率の分散の大きさ」の教材になります |
| 場別 | `stadiumId`(24 場) | 場ごとの得意・不得意。ただし 1 場あたりの n は 24 分の 1 になるので、月単位では多くの場が n < 20 の参考値のままです |
| グレード別 | `grade`(SG / PG1 / G1 / G2 / G3 / 一般、空文字は「不明」) | 一般戦と記念で回収率が違うか。強さpt の材料である選手・モーター成績が、格上のメンバー構成でも効いているか |
| 買い目点数別 | `betCount` を 1〜4 / 5〜9 / 10〜19 / 20 点〜 に区切る | 候補窓 ±0.10 に何艇入ったか(=モデルの迷い)と成績の関係。点数が多いセルは的中率が高くても購入額が膨らむので、回収率が伸びない構造が見えます |
| 本命枠番別 | 直前 AI 評価で `strengthPt` が最大の艇の枠番(同点は若い枠番) | 1 号艇本命のレースと、2〜6 号艇本命のレースで回収率がどう違うか。イン有利の場で 1 号艇以外を本命にしたときの成績が取り出せます |
| 配当帯別 | 確定 3 連単配当を 〜999 / 1,000〜2,999 / 3,000〜9,999 / 1 万円〜 に区切る(欠損は「不明」) | 堅い決着と荒れた決着のどちらで払戻を取れているか。**的中の有無に関わらず** 配当で区分するので、「荒れたレースをどれだけ落としているか」も見えます |
| 風速別 | 確定結果の風速を 0〜1 / 2〜3 / 4〜5 / 6〜7 / 8 m/s〜 に区切る(欠損は「不明」) | 強風時に展示・気象成分が効いているか。気象pt(第 4 章)の妥当性を事後に確かめる軸です |

ビンの境界はすべて定数(`BET_COUNT_BINS` / `PAYOUT_BANDS` / `WIND_BINS`)で、実データの分布を見て動かせるようにしてあります。配当帯の「1 万円」は万舟の閾値 `BIG_PAYOUT_THRESHOLD_YEN` と同じ値で、3 連単配当分布の上位 16% がここに入ります。boatracecsv `docs/design/ana_prediction.md` §2.2 の集計では、1 万円以上はレースの 16.3% にすぎない一方で払戻総額の 67.6% を占めます(母数は同 §2.1 と同じ 42,090 レースと考えられます)。

### 監査できる集計にする

1 レースは各軸へ **ちょうど 1 回** 加算されます。したがって `byStadium` / `byGrade` / `byBetCount` / `byHonmeiWaku` の `raceCount` を合計すると `total.raceCount` と一致し、`byPayoutBand` / `byWindSpeed` は「不明」バケットを含めれば一致します。集計結果を目で検算できるよう、欠損レースを黙って落とさず「不明」に立てるのがポイントです。なお集計対象は確定済みレースに限るので、確定結果が必ず持つ風速は実際には「不明」に入りません。配当は結果とは別の CSV(`results/payouts`)から来るため欠損しえます。

### n < 20 は淡色にする

各セルは n(レース数)とセットで出し、`n < LOW_N`(= 20)のセルは行ごと灰色(`text-gray-400`)にして区分名の横に「参考」と添えます。回収率が 100% 以上のセルは通常なら緑の太字で強調しますが、n < 20 のときはこの強調も外します。20 レース程度では的中率が 1 レースで 5pt 動き、回収率は万舟 1 本で数十 pt 動く(購入額が 11 点 × 20 レース ≒ 2 万円台のところに 1 万円が乗る)ので、色を付けると「この場は得意」と誤読させるためです。しきい値 20 は統計的に導いた値ではなく、「1 日〜数日ぶんの n」という運用上の目安です。統計的に意味のある差を言うには第 9 章の検出力の計算が要り、月単位の 1 セルでは届かないと考えられます。

:::message
**軸を増やすほど、各セルの n は減ります。** 7 軸の表は「どこで効いているか」の仮説を立てる道具で、仮説を検証する道具ではありません。検証は第 9 章の方法(control と同一レースのペア比較)で別途行います。
:::

## 3. 体験指標

回収率だけでは、「当たらないが当たれば大きい」穴予想(`v9_suji` / `v10_kimarite`)の価値を測れません。回収率が同水準でも、5 点で 3,000 円台の配当を取る予想と 11 点で 2,000 円台を取る予想では、使う側の体験がまったく違うからです。そこで `predictor-stats.ts` は回収率に加えて次の 4 つを集計します(boatracecsv `docs/design/ana_prediction.md` §7)。

| フィールド | 内容 |
| --- | --- |
| `averagePayoutYen` | 平均配当。分母は **的中数**(レース数ではない) |
| `averageBetCount` | レースあたりの購入点数 |
| `bigHitCount` | 万舟(3 連単 1 万円以上)の的中数 |
| `bigHitPer10kYen` | **賭け金 1 万円あたり** の万舟的中数 |

### 万舟は本数で比べない

万舟の素の本数は、点数を多く買う予想者ほど増えます。設計時のテスト期間(3,527 レース、control と同一レース)では、穴予想(5.0 点)が 21 本、control(11.5 点)が 40 本で、本数では穴予想が負けています。しかし control は 2.3 倍の金額を賭けているので、賭け金 1 万円あたりに直すと 0.12 対 0.10 で逆転します。比較には必ず `bigHitPer10kYen` を使い、`bigHitCount` は表示しても比較の根拠にしない、というのが集計側の約束です。

本番投入後の実測(2026-08-13〜08-22、両案同一の 1,511 レース)でも、A 案 `v9_suji` は平均配当 3,949 円・万舟 0.133 本/1 万円、B 案 `v10_kimarite` は 3,035 円・0.066 本/1 万円で、体験指標では A 案が上でした。それでも A 案を退役させたのは、第 21 章で扱うとおり主判定が 3 連単 log-loss だったからです。

### 目標値は置くが有意差判定はしない

体験指標には「平均配当は control の 1.5 倍以上」「点数は半分以下」「万舟/1 万円は control より多い」という目標値を置いていますが、有意差の判定はしません。回収率の 95% CI が 3,527 レースで ±13.3pt あり、万舟/1 万円の差(B 案 − A 案)も −0.045 に対して CI が [−0.108, +0.017] と値そのものより広いため、月単位の運用データでは検出力が足りないからです。必要サンプル数の逆算は第 9 章に譲ります。ここでは「目標値と実測を並べて眺める」以上のことを画面に語らせない、という線引きだけ覚えてください。

なお 2026 年 9 月時点の実装では、これらのフィールドは `stats.json` に書き出されていますが、`/predictors/` ページの表には載っていません(ページ側の型定義が回収率までしか読んでいません)。設計書の記録用途で先に集計を整えた形です。

## 4. 集計の実装

### パイプラインの中の位置

fun-site のバッチ(第 13 章)は、当日の `RacePrediction[]` を組み立てた直後の Step 2.5 で 2 つの集計器を呼びます。

```
prediction-builder → [Step 2.5] collectPredictionDigests → buildPredictorStats
                                                          → buildPredictorBreakdown
                   → site-builder(astro build → deploy)
```

Step 2.5 は `try/catch` で包まれ、失敗しても **非致命** です。`stats.json` / `breakdown.json` が無ければ `/predictors/` と `/stats/` は「集計データがまだ生成されていません」の注意書きだけを出し、レース詳細ページのビルドとデプロイは止まりません。Astro 側はこの 2 つの JSON を静的 `import` ではなく Vite の `import.meta.glob` で読んでおり、ファイルが無くてもビルドが落ちない形にしてあります。予想ページの配信を統計ページの都合で止めない、という優先順位の表れです。

### ダイジェストへの射影

集計器は `RacePrediction` を受け取りません。`RacePrediction` は出走表・近況・過去 10 走を抱えて 1 件 100KB 超あり、active 予想者の `startedAt` から当日まで(数か月)を丸ごとメモリに載せると、2Gi のコンテナで約 1GB の Node ヒープ上限を超えて OOM でクラッシュします。そこで `toPredictionDigest(pred)` が集計に必要な項目だけを抜いた `PredictionDigest` に畳み、集計器にはこれだけを渡します。

| レース単位 | 予想者単位 |
| --- | --- |
| `raceCode` / `raceDate` / `stadiumId` / `grade` | `betCount` / `betCostYen` / `payoutYen`(直前買い目) |
| `settled`(`isSettledResult` の結果) | `dailyHit` / `realtimeHit` |
| `windSpeed`(確定結果の風速) | `honmeiWaku`(直前評価の `strengthPt` 最大艇) |
| | `sanrentanPayout`(確定 3 連単配当) |

1 レースが数百バイト × 予想者数になり、数か月ぶんでも数 MB に収まります。7 軸のどれを足すか(たとえば風速)は、この型に何を残すかで決まります。射影の入口を `toPredictionDigest` の 1 か所にしているのは、`/predictors/` と `/stats/` が同じ母数・同じ的中判定を見ることを保証するためです。

### 日別の incremental キャッシュ

過去日の結果は確定後に変わらないので、日ごとのダイジェストを `gs://${GCS_DATA_BUCKET}/_meta/prediction-digests/{date}.json` にキャッシュします。`collectPredictionDigests({ dates, raceDate, currentPredictions })` の動きは次のとおりです。

- **当日**はメモリ上の `RacePrediction[]` から毎回作り直し、同パスに上書き保存する(結果が順次確定するため)
- **過去日**はまずキャッシュを読む。無い、または `schemaVersion` が `PREDICTION_DIGEST_SCHEMA_VERSION` と違うときだけ、`predictions/{date}/*.json` を 1 件ずつ射影しながら読んで保存する
- 元データが **空の日は保存しない**。一覧取得の一時失敗を「レース無し」として固定してしまうのを防ぐため
- 過去日は最大 4 日並列、日の中では 16 並列で読む

ダイジェストの形を変えるときは `PREDICTION_DIGEST_SCHEMA_VERSION` を上げます。次のビルドで全日が作り直されるので、バージョンを上げ忘れると「古い形のキャッシュと新しい集計器」が混ざる事故になります。バックフィル(`BUILD_TARGET_DATE`)ではその日が `raceDate` になるため当日扱いで上書きされ、手動で捨てたい日は GCS のファイルを消せば済みます。

### 2 つの集計器

`buildPredictorStats(digests)` と `buildPredictorBreakdown(digests)` は同じ配列を受け取ります(元 JSON を 2 回読まない)。どちらも純関数 `aggregatePredictorStats` / `aggregatePredictorBreakdown` を持ち、テストはそこに対して書きます。

- **predictor-stats**: 予想者 × 月のバケットに `accumulate()` で足し込み、月次と通算を `stats.json` に書く。体験指標もここで出す
- **predictor-breakdown**: 予想者ごとに `AxisAggregator` を 6 つ持ち、1 レースを各軸へ 1 回ずつ `add()` する。時系列は日付 → アキュムレータの Map から累積を作る。`raceCount === 0` のバケットは出さず、表示順はビン定義の順で「不明」は末尾

### 簡略版コード

`bigHitPer10kYen` と、配当帯の 1 軸ぶんを抜き出したものです。実装では `AxisAggregator` クラスが 6 軸を共通化していますが、ここでは配当帯に固定して平たく書いています。

```ts:breakdown-lite.ts
// 集計器が受け取るのは RacePrediction ではなく、この軽量ダイジェストだけ
type PredictorDigest = {
  predictorId: string;
  betCount: number;      // 直前買い目の点数
  betCostYen: number;    // 直前買い目の購入額 (0 なら買い目が組めていない)
  payoutYen: number;     // 直前買い目の払戻額
  realtimeHit: boolean;  // 直前買い目の的中
  sanrentanPayout?: number; // 確定 3連単 配当 (欠損なら undefined)
};
type PredictionDigest = { raceDate: string; settled: boolean; predictors: PredictorDigest[] };

type Metrics = {
  raceCount: number; hitCount: number; hitRate: number | null;
  betCostYen: number; payoutYen: number; recoveryRate: number | null;
};
type Bucket = { key: string; label: string; metrics: Metrics };

const BIG_PAYOUT_THRESHOLD_YEN = 10_000;

/** 賭け金 1 万円あたりの万舟的中数。素の本数は点数を多く買う予想者ほど増えるので使わない。 */
const bigHitPer10kYen = (rows: readonly PredictorDigest[]): number | null => {
  const totalCost = rows.reduce((s, r) => s + r.betCostYen, 0);
  const bigHits = rows.filter((r) => r.realtimeHit && r.payoutYen >= BIG_PAYOUT_THRESHOLD_YEN).length;
  return totalCost > 0 ? bigHits / (totalCost / 10_000) : null;
};

// ---- 1 軸ぶんの集計 (配当帯別) ----
const PAYOUT_BANDS = [
  { key: "band_lt1000", label: "〜999円", max: 999 },
  { key: "band_1000_2999", label: "1,000〜2,999円", max: 2999 },
  { key: "band_3000_9999", label: "3,000〜9,999円", max: 9999 },
  { key: "band_10000_", label: "1万円〜", max: Number.POSITIVE_INFINITY },
] as const;
const UNKNOWN = { key: "unknown", label: "不明" } as const;

const binKeyOf = (value: number) => PAYOUT_BANDS.find((b) => value <= b.max)!.key;

type Acc = { raceCount: number; hitCount: number; betCostYen: number; payoutYen: number };
const finalize = (a: Acc): Metrics => ({
  ...a,
  hitRate: a.raceCount > 0 ? a.hitCount / a.raceCount : null,
  recoveryRate: a.betCostYen > 0 ? a.payoutYen / a.betCostYen : null,
});

export const byPayoutBand = (digests: readonly PredictionDigest[], predictorId: string): Bucket[] => {
  const acc = new Map<string, Acc>();
  for (const race of digests) {
    if (!race.settled) continue;                       // 1〜3 着が揃ったレースだけ
    for (const pp of race.predictors) {
      if (pp.predictorId !== predictorId || pp.betCostYen <= 0) continue; // 直前買い目が組めたレースだけ
      const key = pp.sanrentanPayout === undefined ? UNKNOWN.key : binKeyOf(pp.sanrentanPayout);
      const a = acc.get(key) ?? { raceCount: 0, hitCount: 0, betCostYen: 0, payoutYen: 0 };
      a.raceCount += 1;
      a.hitCount += pp.realtimeHit ? 1 : 0;
      a.betCostYen += pp.betCostYen;
      a.payoutYen += pp.payoutYen;
      acc.set(key, a);
    }
  }
  // 表示順はビン定義の順、「不明」は末尾。n = 0 のビンは出さない
  return [...PAYOUT_BANDS, UNKNOWN]
    .filter((b) => acc.has(b.key))
    .map((b) => ({ key: b.key, label: b.label, metrics: finalize(acc.get(b.key)!) }));
};

export { bigHitPer10kYen };
```

読むときのポイントは 3 つです。

1. 母数の 2 条件(`settled` と `betCostYen > 0`)がループの先頭に **2 行で** 並んでいます。的中率と回収率の分子・分母がここで同時に決まるので、片方だけ条件を変えることができません。
2. 配当帯のキーは「的中したか」を見ずに `sanrentanPayout` だけで決めます。外れたレースも配当帯に入るので、「1 万円〜」の的中率がそのまま「荒れたレースをどれだけ拾えたか」になります。
3. `bigHitPer10kYen` の分母は購入額です。点数が違う予想者を並べる指標は、レース数ではなく金額で正規化します。

## 元資料

- fun-site [`docs/batch.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/batch.md)(4.4 prediction-digest、4.5 predictor-stats、4.6 predictor-breakdown、予想者統計の体験指標)
- fun-site [`docs/web.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/web.md)(`/predictors/`、`/stats/`、`TrendLineChart`)
- fun-site [`docs/data-sources.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/data-sources.md)(`predictors/breakdown.json` のスキーマ)
- fun-site [`docs/domain.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md)(的中率・回収率の母数)
- fun-site [`packages/batch/src/aggregator/prediction-digest.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/prediction-digest.ts) / [`prediction-digest-store.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/prediction-digest-store.ts) / [`predictor-stats.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/predictor-stats.ts) / [`predictor-breakdown.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/predictor-breakdown.ts)
- fun-site [`packages/batch/src/pipeline.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/pipeline.ts)(Step 2.5)
- fun-site [`packages/shared/src/types/predictor-stats.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/types/predictor-stats.ts)、[`packages/shared/src/utils/bet-payout.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/bet-payout.ts)、[`packages/shared/src/utils/race-result.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/race-result.ts)、[`packages/shared/src/utils/one-mark-distance.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/one-mark-distance.ts)
- fun-site [`packages/web/src/pages/predictors/index.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/predictors/index.astro)、[`packages/web/src/pages/stats/index.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/stats/index.astro)、[`packages/web/src/components/TrendLineChart.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/TrendLineChart.astro)
- boatracecsv [`docs/design/ana_prediction.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/ana_prediction.md)(§2.2 配当分布、§7 KPI、§11.2 control の再現、§13.3 判定基準)、[`docs/data/estimate.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md)(現行レジストリ、v9_suji の退役ノート)

## 演習

公開 CSV から control(`v1_basic`)の直前買い目を再現し、配当帯別の回収率を自分で集計してみます。必要な CSV は 4 種類で、すべて `レースコード` で結合できます。

| CSV | 使う列 |
| --- | --- |
| `estimate/v1_basic/YYYY/MM/DD.csv` | `状態 = realtime` の行の `N枠_強さpt` |
| `programs/race_cards/YYYY/MM/DD.csv` | `艇N_全国平均ST`(予測 ST) |
| `results/realtime/YYYY/MM/DD.csv` | `1着_艇番` 〜 `3着_艇番`(確定判定と的中判定) |
| `results/payouts/YYYY/MM/DD.csv` | `3連単_払戻金`(払戻と配当帯) |

買い目の規則は第 8 章のとおりです。1 マーク走行距離 `(1 − 予測ST) + 強さpt/50 − 1.6` を 6 艇ぶん出し、距離の 1 位 ± 0.10 を 1 着候補、2 位 ± 0.10 を 2 着候補、3 位 ± 0.10 を 3 着候補として、同一艇を含まない直積を買い目にします。全国平均 ST が 0.00(実績なし)の艇は 0.25 で補います。

```python:payout_band_recovery.py
"""control (v1_basic) の直前買い目を公開 CSV から簡略再現し、配当帯別の回収率を集計する。

fun-site の computeOneMarkDistances / computeBettingPicks / computeBetPayout /
isSettledResult を Python に写したもの。完全再現ではない (後述)。
"""
import csv
from pathlib import Path
import itertools
import urllib.request
from collections import defaultdict

BASE = "https://boatracecsv.github.io/data"
YEAR, MONTH, DAYS = 2026, 8, range(1, 32)
TOL = 0.10                 # DEFAULT_BETTING_TOLERANCE (全着 ±0.10)
NO_RECORD_ST_FALLBACK = 0.25
BET_UNIT_YEN = 100
BIG_PAYOUT_THRESHOLD_YEN = 10_000
PAYOUT_BANDS = [("〜999円", 999), ("1,000〜2,999円", 2999),
                ("3,000〜9,999円", 9999), ("1万円〜", float("inf"))]


def fetch(path: str) -> list[dict]:
    """公開 CSV を cache/ に落として読む。無い日 (404) は空リスト。"""
    local = Path("cache") / path
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(f"{BASE}/{path}", local)
        except Exception:
            return []
    return list(csv.DictReader(local.open(encoding="utf-8")))


def to_float(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def picks_for(strength: dict[int, float], avg_st: dict[int, float]) -> tuple[list, list, list]:
    """1 マーク走行距離 = (1 − 予測ST) + 強さpt/50 − 1.6 から各着の候補窓を取る。"""
    dist = {b: 1 - (avg_st.get(b) or NO_RECORD_ST_FALLBACK) + strength[b] / 50 - 1.6
            for b in strength}
    ranked = sorted(dist, key=lambda b: dist[b], reverse=True)
    def within(ref_boat):
        return sorted(b for b in dist if abs(dist[b] - dist[ref_boat]) <= TOL + 1e-9)
    return within(ranked[0]), within(ranked[1]), within(ranked[2])


def combos(first, second, third) -> set[tuple[int, int, int]]:
    return {(a, b, c) for a, b, c in itertools.product(first, second, third)
            if len({a, b, c}) == 3}


def band_of(payout: int | None) -> str:
    if payout is None:
        return "不明"
    return next(label for label, mx in PAYOUT_BANDS if payout <= mx)


acc = defaultdict(lambda: dict(n=0, hit=0, cost=0, payout=0))
total = dict(n=0, hit=0, cost=0, payout=0, bets=0, big=0)

for day in DAYS:
    d = f"{YEAR}/{MONTH:02d}/{day:02d}"
    index = {r["レースコード"]: r for r in fetch(f"estimate/v1_basic/{d}.csv")
             if r["状態"] == "realtime"}           # 直前行だけを使う
    cards = {r["レースコード"]: r for r in fetch(f"programs/race_cards/{d}.csv")}
    results = {r["レースコード"]: r for r in fetch(f"results/realtime/{d}.csv")}
    payouts = {r["レースコード"]: r for r in fetch(f"results/payouts/{d}.csv")}

    for code, idx in index.items():
        res, card = results.get(code), cards.get(code)
        if res is None or card is None:
            continue
        top3 = tuple(int(res[f"{k}着_艇番"]) for k in (1, 2, 3) if res.get(f"{k}着_艇番"))
        if len(top3) != 3 or len(set(top3)) != 3:      # isSettledResult
            continue
        strength = {b: to_float(idx[f"{b}枠_強さpt"]) or 0.0 for b in range(1, 7)}
        avg_st = {b: to_float(card[f"艇{b}_全国平均ST"]) or 0.0 for b in range(1, 7)}
        cs = combos(*picks_for(strength, avg_st))
        if not cs:                                       # betCostYen == 0 は母数に入れない
            continue
        sanrentan = payouts.get(code, {}).get("3連単_払戻金")
        sanrentan = int(sanrentan) if sanrentan else None
        hit = top3 in cs
        cost = len(cs) * BET_UNIT_YEN
        pay = sanrentan if (hit and sanrentan is not None) else 0

        for bucket in (acc[band_of(sanrentan)], total):
            bucket["n"] += 1
            bucket["hit"] += hit
            bucket["cost"] += cost
            bucket["payout"] += pay
        total["bets"] += len(cs)
        total["big"] += hit and pay >= BIG_PAYOUT_THRESHOLD_YEN

print(f"{'配当帯':<16}{'n':>6}{'的中率':>9}{'回収率':>9}")
for label, _ in PAYOUT_BANDS + [("不明", None)]:
    a = acc.get(label)
    if not a:
        continue
    print(f"{label:<16}{a['n']:>6}{a['hit']/a['n']:>9.1%}{a['payout']/a['cost']:>9.1%}")
t = total
print(f"\n合計 n={t['n']}  的中率 {t['hit']/t['n']:.1%}  回収率 {t['payout']/t['cost']:.1%}"
      f"  平均点数 {t['bets']/t['n']:.1f}  万舟 {t['big']} 本"
      f"  万舟/1万円 {t['big']/(t['cost']/10_000):.3f}")
```

2026 年 8 月(31 日ぶん)の公開 CSV で実行した結果です。

```
配当帯                  n      的中率      回収率
〜999円              889    84.9%    73.5%
1,000〜2,999円      1602    57.1%    85.5%
3,000〜9,999円      1223    24.9%    86.3%
1万円〜               735     5.2%    70.1%

合計 n=4449  的中率 45.2%  回収率 81.4%  平均点数 11.7  万舟 38 本  万舟/1万円 0.073
```

合計行の平均点数 11.7 点・的中率 45.2% は、設計書に載っている control の実績(11.5〜11.7 点、45.6〜46.6%)とよく一致しています。配当帯別に見ると、〜999 円の帯は 85% 当てても回収率 73.5% にとどまり、1 万円〜の帯は 5% しか当たらないのに回収率 70.1% です。的中率と回収率が別の指標だということが、この 1 表で分かります。

:::message alert
この再現は **簡略版** です。fun-site の集計はビルド時点の `RacePrediction`(その時点の index 行・出走表・結果)から作られるため、後日公開 CSV を読み直した値と一致するとは限りません。また 8 月全体の回収率 81.4% は、設計書の 86.2%(2026 年 7 月までのテスト期間 3,527 レース)とは対象期間が違います。数字を並べて「悪化した」と読まないでください。月単位の回収率は ±10pt 以上動く指標です(第 9 章)。
:::

余力があれば、`band_of()` を風速や本命枠番(`強さpt` 最大の枠)に差し替えて、他の軸も出してみてください。n が 20 を割るセルがどれだけ増えるかを見るのが目的です。
