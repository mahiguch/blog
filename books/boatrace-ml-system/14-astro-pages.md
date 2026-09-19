---
title: "Astro で作る予想ページ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 予想者(モデルのバリアント)ごとの「表示の仕方」と「買い目の作り方」を、コードの分岐ではなくレジストリの宣言として持つ。モデル側で予想者を足したり退役させたりしても UI を触らずに済む構造 |
| システム | pnpm monorepo(shared / batch / web)の役割分担、ゼロ JS の SSG、`PredictorSpec` 駆動の描画、ページと JSON / CSV の対応、艇色を基底にした色設計、iPhone 幅 375px を基準にした実測ベースの列設計、`border-separate` を選ぶ理由 |

第 13 章で、fun-site のバッチが Pub/Sub 通知を受けて CSV を取得し、レース 1 件につき 1 つの `RacePrediction` JSON を書き出し、`astro build` を回して GCS にデプロイするところまでを見ました。この章はその `astro build` の中身、つまり `packages/web` が JSON をどうページに変えているかを扱います。Astro の構文そのものは前提知識とし、「どのページが何を読むか」「予想者の増減にどう追従するか」「なぜその見た目なのか」に絞ります。

## 1. パッケージ構成

fun-site は pnpm workspace の monorepo です(Node.js >= 22、pnpm 10.x)。`docs/development.md` にある構成をそのまま引用します。

```
fun-site/
├── packages/
│   ├── shared/   # 共通型・定数・ユーティリティ
│   ├── batch/    # CSV 取得 → JSON 生成 → Astro ビルド → GCS デプロイ
│   └── web/      # Astro SSG フロントエンド
├── infra/        # Terraform(GCP インフラ)
├── docs/
├── scripts/      # ワンショットの運用スクリプト
├── cloudbuild.yaml
└── package.json
```

3 つのパッケージの責務は次のとおりです。

| パッケージ | 中身 | 依存 |
| --- | --- | --- |
| `@fun-site/shared` | 型(`RacePrediction` / `PredictorPrediction` / CSV 行の型)、定数(24 場マスタ `STADIUMS`、艇色 `BOAT_COLORS`、グレードバッジ `RACE_GRADES`)、予想者レジストリ `predictors.ts`、買い目・走行距離・各 pt の再計算ユーティリティ | zod のみ |
| `@fun-site/batch` | 第 13 章。fetcher / prediction-builder / aggregator / site-builder | shared |
| `@fun-site/web` | Astro 5 + Tailwind CSS 4 の静的サイト。`src/pages/`、`src/components/`、`src/layouts/BaseLayout.astro`、`src/lib/data.ts` | shared、astro |

なぜ shared を分けるのか。batch は「集計対象になる買い目」を作り、web は「画面に出す買い目」を描きます。この 2 つが別々の判断をすると、画面に出ている買い目と回収率の母数になっている買い目が食い違います(第 8 章)。予想者ごとの挙動を決める唯一の場所を shared に置き、batch と web の両方がそこを経由することで、構造的に食い違えないようにしています。

shared の `package.json` は `exports` に条件を持ち、`production` では `dist/index.js`、それ以外では `src/index.ts` を解決します。batch の本番コンテナは `--conditions=production` で tsc の出力を使い、web の開発サーバーはソースをそのまま読みます。

web 側の設定は最小です。

```ts:packages/web/astro.config.ts
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";

export default defineConfig({
  output: "static",
  site: process.env["SITE_URL"] ?? "https://fun-site.example.com",
  vite: { plugins: [tailwindcss()] },
});
```

`tailwind.config.*` はありません。Tailwind v4 は CSS ファースト設定で、`src/styles/global.css` の `@import "tailwindcss";` と `@source` ディレクティブだけで動きます(`@source` の役割は第 5 節で扱います)。

開発サーバーは `pnpm --filter @fun-site/web run dev` で `http://localhost:4321` に立ちます。`src/data/races/` に JSON が無いと「本日の予想データはまだありません」と表示されるので、実データで確認したい場合はバッチを一度回すか、フィクスチャ JSON を `src/data/races/{YYYY-MM-DD}/` に置きます。ビルド対象日は環境変数で制御します。

| 環境変数 | 効果 |
| --- | --- |
| なし | JST 当日のみビルド |
| `BUILD_TARGET_DATE=YYYY-MM-DD` | 明示指定(CI / backfill 用) |
| `BUILD_ALL_DATES=1` | `src/data/races/` 配下の全日付(ローカル開発用) |

既定が当日 1 日分だけなのは、2 分毎に起動されるビルドが過去日の JSON まで読み込んでページ数が線形に増えるのを防ぐためです。過去日の HTML は第 13 章のデプロイフィルタで GCS に残置されるので、再ビルドしなくても URL は生き続けます。

## 2. TypeScript 側の PredictorSpec

第 10 章の boatracecsv 側レジストリ(`scripts/boatrace/predictors/registry.py`)と対になるのが、`packages/shared/src/predictors.ts` の `PredictorSpec` です。Python 側の `PredictorSpec` が持つのは `predictor_id` / `display_name` / `slot` / `status` / `started_at` / `component_keys` の 6 つで、これは TypeScript 側にも同名(camelCase)で存在します。TypeScript 側にはそれに加えて 2 種類のフィールドがあります。

**表示用のフィールド**

- `icon` / `badgeTailwindClass`: 直前買い目が的中したときのアイコンとバッジ配色。本命 🎯 / スジ 🧩 / 穴 💎。active な予想者の間で重複しない値を必ず指定します(アイコンだけでどの予想者が当たったか判別できるようにするため)。テストで一意性を検査しています。

**挙動フラグ**

| フラグ | 意味 | 解決ヘルパー |
| --- | --- | --- |
| `useEstimatedST` | 1 マーク走行距離(= 買い目の選定値)の予測 ST に、全国平均 ST ではなく AI 推定 ST(`estimate/racer_st`)を使う | `oneMarkDistanceOptionsFor()` |
| `strengthOnlyBetting` | 買い目候補の窓を走行距離 ±0.10 ではなく強さpt ±5.0pt にする(距離式が強さpt/50 を項に持つので等価スケール) | `bettingBasisFor()` / `bettingToleranceFor()` |
| `bettingStyle` | 買い目をどこから得るか。`"formation"`(既定。fun-site が計算)/ `"suji"` / `"kimarite"`(boatracecsv が確定させた出目を CSV から読む) | `bettingStyleFor()` |
| `showsAiPanels` | 予想者カードに「AI 評価の内訳」「スタート予想」「1 マーク予想」の 3 パネルを出すか。未指定 = true | `showsAiPanelsFor()` |

これらが Python 側に無いのは、買い目の生成が fun-site 側にあるからです(第 8 章)。boatracecsv は強さpt(index CSV)を出すところまでで、それを買い目に変える規則は fun-site の関心事です。`showsAiPanels` に至っては純粋に表示専用で、買い目にも回収率にも集計にも影響しないため、Python 側に対応フィールドを持たせる理由がありません。

ただし ID と `startedAt` と `componentKeys` は両側で必ず同期させます。fun-site の fetcher は `activePredictors()` をループして `data/estimate/{predictor_id}/YYYY/MM/DD.csv` を取りに行き、`componentKeys` の順で CSV 列(`1枠_枠番pt` / `1枠_寄与_枠番pt` …)をパースします。第 13 章の build-state も `index:{predictor_id}` をキーに generation を追跡します。つまり Python 側で予想者を足しても TypeScript 側に足さなければ、fun-site はその CSV の存在を知らないままです。逆に TypeScript 側だけに足せば存在しない CSV を取りに行きます。`predictors.test.ts` には `matches the boatracecsv registry started_at` というテストがあり、少なくとも開始日のずれは CI で検出されます。

### 簡略版コード(TypeScript)

実装から本質だけを抜き出すと次の 60 行になります。関数名は実装と同じです。

```ts:predictors.ts
/** 各予想者が採用しうる成分キー。CSV 列名 `N枠_{ラベル}` への逆引きにも使う。 */
export type ComponentKey = "waku" | "course" | "racer" | "motor" | "motor4" | "exhibit" | "weather";

export const COMPONENT_LABELS: Readonly<Record<ComponentKey, string>> = {
  waku: "枠番pt", course: "コースpt", racer: "選手pt", motor: "モーターpt",
  motor4: "モーターpt", exhibit: "展示pt", weather: "気象pt",
};

export type PredictorSpec = {
  readonly id: string;                        // 退役後も再利用しない
  readonly displayName: string;
  readonly slot: number;                      // active 内の表示順
  readonly status: "active" | "retired";
  readonly startedAt: string;                 // 累計回収率の起点
  readonly componentKeys: readonly ComponentKey[]; // 順序 = CSV 列順
  readonly icon?: string;                     // 的中アイコン。active 間で一意
  readonly badgeTailwindClass?: string;
  // ---- 挙動フラグ(boatracecsv 側 registry.py には無い。買い目は fun-site で組むため)
  readonly useEstimatedST?: boolean;          // 1 マーク距離の予測 ST に AI 推定 ST
  readonly strengthOnlyBetting?: boolean;     // 候補窓を距離 ±0.10 → 強さpt ±5.0
  readonly bettingStyle?: "formation" | "suji" | "kimarite"; // 買い目をどこから得るか
  readonly showsAiPanels?: boolean;           // 表示専用。未指定 = true
};

export const PREDICTORS: readonly PredictorSpec[] = [
  { id: "v1_basic", displayName: "本命予想", icon: "🎯",
    badgeTailwindClass: "bg-amber-100 text-amber-800 border-amber-300",
    slot: 1, status: "active", startedAt: "2026-05-01",
    componentKeys: ["waku", "racer", "motor", "exhibit", "weather"] },
  { id: "v5_slit", displayName: "スリット予想", slot: 5, status: "retired", startedAt: "2026-07-21",
    componentKeys: ["waku", "racer", "motor", "exhibit", "weather"], useEstimatedST: true },
  { id: "v10_kimarite", displayName: "穴予想", icon: "💎",
    badgeTailwindClass: "bg-cyan-100 text-cyan-800 border-cyan-300",
    slot: 10, status: "active", startedAt: "2026-08-13",
    componentKeys: ["waku", "racer", "motor", "exhibit", "weather"],
    bettingStyle: "kimarite", showsAiPanels: false },
];

export const activePredictors = (): readonly PredictorSpec[] =>
  PREDICTORS.filter((p) => p.status === "active").toSorted((a, b) => a.slot - b.slot);

export const predictorById = (id: string): PredictorSpec | undefined =>
  PREDICTORS.find((p) => p.id === id);

/** fetcher が取りに行く CSV のリポジトリ相対パス。 */
export const predictorCsvPath = (p: PredictorSpec, d: { year: number; month: number; day: number }) =>
  `data/estimate/${p.id}/${d.year}/${String(d.month).padStart(2, "0")}/${String(d.day).padStart(2, "0")}.csv`;

// ---- 挙動フラグの解決。バッチ(集計)と web(表示)は必ずこれらを通す(第 8 章)
export const bettingStyleFor = (id?: string): "formation" | "suji" | "kimarite" => {
  const s = id ? predictorById(id)?.bettingStyle : undefined;
  return s === "suji" || s === "kimarite" ? s : "formation";
};
export const bettingBasisFor = (id?: string): "distance" | "strength" =>
  id && predictorById(id)?.strengthOnlyBetting === true ? "strength" : "distance";
export const oneMarkDistanceOptionsFor = (id?: string) => ({
  useEstimatedST: id ? predictorById(id)?.useEstimatedST === true : false,
});
export const showsAiPanelsFor = (id?: string): boolean =>
  !id || predictorById(id)?.showsAiPanels !== false;
```

実装では `PREDICTORS` に v1 〜 v10 の全 10 件が並び、退役した予想者もエントリと過去データを保持したまま `status: "retired"` になっています。`activePredictors()` から外れるので、fetcher / build-state / 各集計の対象からは自動的に外れます。解決ヘルパーが `predictorById(id)?.flag === true` という形で未登録 ID や未指定を既定値に倒しているのは、過去日の JSON に退役予想者や旧スキーマが残っているためで、レジストリに無い ID が来ても描画が落ちないようにしています。

:::message
現在の active は、この原稿執筆時点(2026 年 9 月)の `predictors.ts` では `v1_basic`(本命予想)と `v10_kimarite`(穴予想)の 2 者です。`v9_suji`(スジ予想)は 2026-08-22 に退役しました。一方 `docs/architecture.md` には「現行 active は v1_basic / v9_suji / v10_kimarite の 3 者」という記述が残っており、`docs/web.md` にもスジ予想を active 扱いした説明(当日サマリーの 3 カードなど)が残っています。ドキュメントはレジストリの変更に追従が遅れることがあるので、active の正はコード(`predictors.ts`)で確認してください。
:::

## 3. spec 駆動描画

レース詳細ページ(`race/[date]/[stadiumId]/[raceNumber].astro`)は `RacePrediction.predictions[]` をループして、予想者ごとに `PredictorCard` を縦に並べます。カードの中身は買い目・回収率・AI 評価チャート・スタート予想図・1 マーク予想図ですが、「どのカードに何を出すか」は予想者によって違います。この出し分けをどこに書くかが、この節の主題です。

### ハードコード列挙だった頃

2026 年 7 月 22 日まで、レース詳細ページの出し分けは slot と ID の列挙でした。当時のコードの要点だけ引用します。

```astro
startPrediction={
  pp.predictorId === "v5_slit"
    ? (prediction.startPredictionEstimated ?? prediction.startPrediction)
    : pp.slot === 1 || pp.slot === 2 || pp.slot === 3 || pp.slot === 4
      ? prediction.startPrediction
      : undefined
}
oneMarkAiEvaluation={
  pp.slot === 1
    ? prediction.aiEvaluation
    : pp.slot === 2 || pp.slot === 3 || pp.slot === 4 || pp.slot === 5
      ? (pp.aiEvaluationRealtime ?? pp.aiEvaluationDaily)
      : undefined
}
useOneMarkEstimatedST={pp.predictorId === "v5_slit"}
```

これは UI の中に第 2 のレジストリを持っている状態です。予想者を足すたびに `predictors.ts` とこの分岐の両方を更新しなければならず、片方を忘れても型エラーにはなりません。実際に忘れました。2026-07-22 に `v6_course`(コース予想、slot=6)を投入したとき、レジストリには追加したものの、この分岐には slot=6 が無かったため、コース予想のカードにはスタート予想図も 1 マーク予想図も recipe 注記も出ていませんでした。

### predictorById() に一般化する

翌日 2026-07-23 に `v7_aggregate`(統合予想)を投入する際、この分岐を `predictorById()` で引いた `PredictorSpec` 駆動に書き換えました。`docs/architecture.md` の経緯には「これに伴い、それまで描画分岐に未追加だった `v6_course` のスタート予想図・1 マーク予想図・recipeNote も表示されるようになった」とあります。バグを直そうとして直ったのではなく、分岐を消したら副作用として直った、という順序です。

現在のコードから、出し分けに関わる部分を抜き出します。

```astro:race/[date]/[stadiumId]/[raceNumber].astro
{predictorPredictions.map((pp) => {
  // 描画分岐はレジストリ (predictors.ts) の PredictorSpec 駆動にする。
  const spec = predictorById(pp.predictorId);
  // 1マーク距離 (= 買い目 = 回収率) の予測 ST。ここは A/B の対象なので触らない。
  const usesEstimatedST = spec?.useEstimatedST === true;
  // スタート予想図は予想者に依らず AI 推定 ST 版 (帯つき)。無ければ全国平均 ST の共通図。
  const startPrediction = prediction.startPredictionEstimated ?? prediction.startPrediction;
  const oneMarkAiEvaluation =
    pp.slot === 1 ? prediction.aiEvaluation : (pp.aiEvaluationRealtime ?? pp.aiEvaluationDaily);
  const showsAiPanels = showsAiPanelsFor(pp.predictorId);
  return (
    <PredictorCard
      prediction={pp}
      racers={prediction.racers}
      showChart={showsAiPanels}
      startPrediction={showsAiPanels ? startPrediction : undefined}
      oneMarkAiEvaluation={showsAiPanels ? oneMarkAiEvaluation : undefined}
      useOneMarkEstimatedST={usesEstimatedST}
    />
  );
})}
```

ポイントは 3 つです。

1. **買い目に効くフラグと、表示にしか効かないフラグを分ける。** `usesEstimatedST` は 1 マーク距離、つまり買い目と回収率に効くので、必ず spec から解決します。一方スタート予想図は表示専用で買い目に効かないため、2026-08-11 に予想者に依らず AI 推定 ST 版(予測区間の帯つき、第 15 章)へ統一しました。`useEstimatedST` な予想者が全て退役しても帯を出し続けられるよう、図の側はフラグから切り離してあります。
2. **3 パネルの表示可否は `showsAiPanelsFor()` で決める。** `v10_kimarite` のように買い目が CSV 由来で 1 マーク走行距離を使わない予想者に図を出したままだと、「この図から買い目が出ている」と読者に誤読させます。また 3 パネルは index / 強さpt が同値の予想者間ではほぼ同じ絵になり、本命予想のカードに出ているぶんと重複します。2026-08-15 にこのフラグを新設し、現行 active では本命予想のカードにだけ 3 パネルが出ます。
3. **`PredictorCard` は spec を知らない。** カードは渡された prop を描くだけで、予想者 ID で分岐しません。分岐はページ側の数行に集約されています。

同じ変更を的中表示にも適用しました。1R-12R リンクバーの的中アイコンとレース結果の的中バッジは、2026-08-12 までは「slot=1 と副予想者(slot=4 → slot=2 フォールバック)」の 2 者ハードコードで、`v4_motor` / `v5_slit` の退役後は副予想者ぶんが常に非表示になっていました。`PredictorSpec` に `icon` / `badgeTailwindClass` を持たせ、`getPredictorBadge(id)` 経由で解決することで、直前買い目が的中した予想者ぶんを slot 昇順に並べるだけの実装に変わり、予想者の増減に自動追従します。

残っているハードコードも正直に書いておきます。`recipeNote`(本命予想からの recipe 差分を説明する日本語の注記)だけは ID ごとの文字列分岐がページに残っています。これは退役予想者の過去日ページでしか表示されず、文言そのものが予想者固有のため、spec に移す価値が薄いと判断しました。

## 4. ページ構成

### URL とデータの対応

ランタイムの fetch は一切ありません。すべてのページはビルド時に `src/data/` 配下の JSON を読みます。`packages/web/src/` には `<script>` タグも `client:` ディレクティブも存在せず、配信される HTML には JavaScript が含まれません。折れ線グラフ(`TrendLineChart`)やスタート予想図の SVG も Astro がビルド時にインライン SVG として生成します。

| URL | ファイル | 読むデータ | 関連章 |
| --- | --- | --- | --- |
| `/` | `index.astro` | `races/{当日}/*.json`、`_meta/series-summary.json` | |
| `/stadium/{01-24}/` | `stadium/[stadiumId]/index.astro` | 同上(会場で絞る) | |
| `/race/{date}/{場}/{R}/` | `race/[date]/[stadiumId]/[raceNumber].astro` | `races/{date}/{raceCode}.json`(1 レース 1 ファイル) | 本章、第 15 章 |
| `/race/{date}/{場}/{R}/racers/` | `…/[raceNumber]/racers.astro` | 同じ JSON の `recentForm` | 第 16 章 |
| `/race/{date}/{場}/{R}/motors/` | `…/motors.astro` | 同じ JSON の `motorPtHistory` / `motorPtBasis` / `motorPtBaseline` | 第 16 章 |
| `/race/{date}/{場}/{R}/lanes/` | `…/lanes.astro` | 同じ JSON の `wakuPtBasis` | 第 16 章 |
| `/race/{date}/{場}/{R}/exhibition/` | `…/exhibition.astro` | 同じ JSON の `preview` / `exhibitPtBasis` | 第 16 章 |
| `/race/{date}/{場}/{R}/weather/` | `…/weather.astro` | 同じ JSON の `preview.weather` / `weatherPtBasis` | 第 16 章 |
| `/predictors/` | `predictors/index.astro` | `predictors/stats.json` | 第 17 章 |
| `/stats/` | `stats/index.astro` | `predictors/breakdown.json` | 第 17 章 |
| `/archive/` | `archive/index.astro` | `_meta/dates.json` | |
| `/archive/{date}/` | `archive/[date].astro` | `races/{date}/*.json`、`_meta/dates.json` | |

JSON を読む関数は `src/lib/data.ts` に集約されています。`loadPredictions(date)` は `src/data/races/{date}/*.json` を全件読んで旧スキーマを除外し、`loadAvailableDates()` は既定で JST 当日 1 件だけを返します。`stats.json` と `breakdown.json` は静的 import ではなく `import.meta.glob` で読んでいます。集計バッチは非致命で、初回ビルドや集計失敗時にはファイルが存在しないため、静的 import だとビルドごと落ちてしまうからです。

### JSON と上流 CSV の対応

`RacePrediction` はバッチが複数の CSV を 1 レース単位に結合したものです。主要なフィールドがどの CSV から来るかを `docs/data-sources.md` から整理します。

| `RacePrediction` のフィールド | 上流 CSV(`data/` 以下) | 画面での役割 |
| --- | --- | --- |
| `raceName` / `grade` / `votingDeadline` | `programs/title` | ヘッダ、1R-12R バー |
| `racers[]`(選手・モーター・全国平均 ST・節間成績) | `programs/race_cards` | 出走表、今節成績 |
| `startPrediction` | `previews/stt` + `race_cards` | スタート予想(進入コース) |
| `startPredictionEstimated` | `estimate/racer_st` | スタート予想図(帯つき) |
| `preview` | `previews/tkz` / `sui` / `original_exhibition` | 直前情報 |
| `tokutenHayami` | `previews/tokuten_hayami` | 得点率早見 |
| `waku10` | `programs/waku10` | 枠番別過去 10 走 |
| `recentForm` | `programs/recent_national` / `recent_local` | 選手詳細 |
| `racers[].motorStats` / `motorPtHistory` | `programs/motor_stats` / `estimate/motor_pt/{runs,motors,baseline}` | 出走表、モーター詳細 |
| `predictions[]`(予想者ごとの AI 評価・買い目・回収率) | `estimate/{predictor_id}`、`estimate/suji`、`estimate/kimarite/picks` | 予想者カード |
| `raceResult` / `racePayout` | `results/realtime` / `results/payouts` | レース結果、的中判定、回収率 |
| `wakuPtBasis` / `weatherPtBasis` / `exhibitPtBasis` | `estimate/stadium/win_rate.csv` / `sui_params.csv` / `weights/{predictor_id}/YYYY-MM.csv` | 検算ページ(第 16 章) |

![ページと JSON と CSV の対応](/images/boatrace-ml-system/astro-pages-data-flow.png)
<!-- 図: 左に上流 CSV 群(programs / previews / estimate / results)、中央に batch が生成する JSON(races/{date}/{raceCode}.json、predictors/stats.json、predictors/breakdown.json、_meta/dates.json、_meta/series-summary.json)、右に Astro のページ(/、/stadium、/race 詳細と 5 つの検算ページ、/predictors、/stats、/archive)。矢印で「どの JSON をどのページが読むか」を結ぶ。全部ビルド時、ランタイム fetch なし、と注記 -->

### レース詳細ページのセクション順

レース詳細ページはセクションを「レース結果 → 出走表 → 直前情報 → 枠番別過去 10 走 → 今節成績 → 得点率早見 → 荒れ度メーター → 予想者カード」の順に並べます。出走表まわりの事実情報を出走表の直下にまとめ、予想(荒れ度メーターと予想者カード)をその下に置く、という方針です。荒れ度メーターは予想者に紐づかないレース単位の値なので、予想者カードの外に 1 回だけ置きます。

各セクションは対応するデータが無ければ描画しません。`docs/domain.md` §4 のフォールバック表を引用します。

| 状況 | 表示 |
| --- | --- |
| `previews/stt` 取得済み | 実測の進入コース・スタート展示を表示 |
| `previews/stt` 未取得 | 進入コース = 枠番で仮表示 |
| index の `状態=daily` | 寄与pt から展示・気象を除外し、3 要素のみ表示 |
| index の `状態=realtime` | 5 要素すべて表示 |
| `results/realtime` 取得済み | レース結果セクションを表示 |
| `results/realtime` 未取得 | 結果セクションは非表示 |
| `results/payouts` 取得済み | 「もし買ったら」セクションと当日サマリーを表示 |
| `results/payouts` 未取得 | そのレースは集計から除外 |

朝(daily)と直前(realtime)で表示が変わるのは、展示pt と気象pt が直前情報由来の成分で、朝バッチ時点では中立値 50 に固定されるからです(第 4 章)。`PREVIEW_DERIVED_COMPONENTS` に列挙された成分は、daily 評価では AI 評価バーの凡例自体が出ません。凡例が出ないと検算ページへの導線も消えるので、直前情報セクションの見出し右に「展示ptの詳細 ▸」「気象ptの詳細 ▸」のリンクを別に置いています。

### なぜゼロ JS で足りるのか

このサイトが JavaScript を持たないのは思想というより結果です。ページは preview-realtime の更新のたび(最小 2 分間隔)にフルリビルドされるため、「最新の値を取りに行く」処理をクライアントに持たせる必要がありません。表示するのは確定した値の表と図で、ユーザー操作で変化する状態もありません。状態が無ければ JS も要らず、HTML と CSS だけを CDN に置けば、配信側の関心は第 13 章で見た Cache-Control(`.html` は no-cache、`_astro/` は immutable)だけになります。

## 5. 色とレイアウト

### 艇色を基底にする

ボートレースでは艇番ごとに色が決まっています。`packages/shared/src/constants/boat-colors.ts` はそれをそのまま定数にしたものです。

```ts:boat-colors.ts
export const BOAT_COLORS = {
  1: { name: "白", hex: "#FFFFFF", textHex: "#000000" },
  2: { name: "黒", hex: "#000000", textHex: "#FFFFFF" },
  3: { name: "赤", hex: "#E5002D", textHex: "#FFFFFF" },
  4: { name: "青", hex: "#0047AB", textHex: "#FFFFFF" },
  5: { name: "黄", hex: "#FFD700", textHex: "#000000" },
  6: { name: "緑", hex: "#008000", textHex: "#FFFFFF" },
} as const;
```

この 6 色を全 UI の基底にし、他の色はそれと衝突しないように決めています。ルールは次のとおりです。

- **バッジの背景色は枠番(艇番)、バッジ内の数字は進入コース。** 今節成績表と枠番別過去 10 走で共通の規則です。ボートレースは枠番と進入コースがずれることがあり(前付け)、この 2 つを 1 つのバッジで同時に表せます。1 号艇の白は地の白と区別がつかないので、1 号艇だけ細いボーダーを付けます。
- **着順には色を付けない。** F(フライング)は赤字、L(出遅れ)は橙字、その他の特殊トークンは灰字と、文字色だけで区別します。着順に背景色を付けると艇色と競合するためです。
- **速さは青、順位は橙。** 直前情報の展示タイム系の列は 1 位を `bg-blue-100`、2 位を `bg-blue-50` で塗り、出走表の 4 指標(平均 ST / 全国勝率 / 当地勝率 / モーター 3 連対率)は 1 位を `bg-amber-200` + 太字、2 位を `bg-amber-100` で塗ります。背景色は内側の `span` ではなく `<td>` に付けてセル枠いっぱいを塗ります(`span` だと文字幅ぶんしか塗られません)。順位は重複を潰した値で取るので、1 位タイが 2 艇いれば両方が濃い色になります。
- **グレードは文字ではなく紫の枠。** 枠番別過去 10 走では、一般戦以外(G3 / G2 / G1 / SG)の走をバッジの太い紫枠で表します。枠番の色と進入コースの数字を保ったままグレードを重ねられます。
- **成分の色は `COMPONENT_COLORS`。** AI 評価バーの積み上げ棒は成分ごとに固定色を持ち、`motor` と `motor4` のように同じラベル「モーターpt」を持つ成分も別色です。

Tailwind のクラス名を shared 側の TypeScript 文字列で持っているもの(グレードバッジの `bg-amber-500 text-white`、的中バッジの `badgeTailwindClass` など)には 1 つ落とし穴があります。pnpm workspace 経由のシンボリックリンクは `node_modules` 扱いになり、Tailwind v4 の既定のコンテンツスキャンから外れます。開発サーバーでは見えていた色が本番ビルドでは消える、という典型的な症状になるため、`global.css` で明示的にスキャン対象に入れています。

```css:packages/web/src/styles/global.css
@import "tailwindcss";
@source "../../../shared/src/**/*.ts";
```

さらに本番はバッチコンテナの中で `astro build` が走るので、`packages/batch/Dockerfile` の runner ステージには tsc の出力(`shared/dist`)だけでなく `shared/src` もコピーしています。`@source` がソースを読めなければ同じ症状が本番だけで再発するからです。

### iPhone 幅 375px を基準にする

このサイトは競艇場やスマートフォンで見られる前提なので、iPhone の 375px 幅で横スクロールなしに読めることを列設計の基準にしています。利用可能幅は 311px です。`BaseLayout` の `<main>` が `px-4`(左右 16px)、各セクションのカードが `p-4`(左右 16px)なので、375 − 64 = 311 になります。

この 311px に対して、各テーブルは実測の min-content 幅で設計されています。

| コンポーネント | 列数 | min-content | 手段 |
| --- | --- | --- | --- |
| 得点率早見(`TokutenHayamiSection`) | 10 列 | 285px | 表 `text-[11px]`、選手名・着順別セル `text-[10px]`、padding `px-0.5`、艇番バッジ `w-4` |
| 直前情報(`RacePreviewSection`) | 9 列(計測項目 3 本の場) | 295px | `px-1`、単位をヘッダ側へ逃がす |
| 出走表(`RacerTable`) | 6 列 | (収まる) | 比較したい 4 指標に列を絞る。2 連対率などの細目は載せない |

`overflow-x-auto` はどのテーブルにも付いていますが、極端に長い選手名や計測項目の多い場のためのフォールバックで、通常時に横スクロールが出ることは想定していません。

出走表を 1 艇 1 カードのリストではなく `<table>` にしたのも同じ理由の裏返しです。カードだと項目が縦に散り、艇どうしを見比べられません。比較したい 4 指標が枠をまたいで同じ列に落ちること、それが 375px に収まること、この 2 つを優先して列を 6 本に絞りました。

予想者カードの 2 つの図(スタート予想と 1 マーク予想)を横並びではなく縦積みにしているのも、iPhone 幅で図がカード幅の半分まで縮むと艇バッジと ST の数字が読めなくなるからです。SVG は `viewBox` + `w-full h-auto` なので、縦積みならカード幅なりに拡大されます。

### border-separate を使う理由

今節成績表(`SessionResultsTable`)だけは他のテーブルと違い、`border-collapse` ではなく `border-separate` です。7 日制の節は 14 走になり iPhone 幅に収まらないので横スクロールさせますが、その際に左端の「枠 + 選手」列を `sticky left-0` で固定し、スクロールしていることが分かるよう右側に影を落とします。この影が `border-collapse` だと描画されません。

```astro:SessionResultsTable.astro
{/* sticky 列の影は border-collapse だと描画されないため border-separate + spacing 0 にし、
     行の区切り線は tr ではなく各セルの border-b で引く */}
<table class="text-[11px] border-separate border-spacing-0">
  <thead>
    <tr class="text-gray-500 text-[10px]">
      <th
        scope="col"
        rowspan="2"
        class="sticky left-0 z-10 bg-white ... border-b border-gray-200 shadow-[3px_0_3px_-1px_rgba(0,0,0,0.12)]"
      >
        枠 / 選手
      </th>
```

`border-separate` にすると `border-spacing-0` でセル間の隙間を消す必要があり、また `tr` に付けた border は separate では描画されないため、行の区切り線は各セルの `border-b` で引きます。ST だけ `text-[8px]` と極端に小さいのは、フライング表記 `F.03` を 20px 幅のセルに収めるためです。

こうした「なぜその値なのか」をコンポーネントのコメントと `docs/web.md` の両方に残しているのは、後から別の人(あるいは数か月後の自分)が「なぜ collapse じゃないのか」「なぜ 8px なのか」と思って戻したときに、同じ問題を踏み直さないためです。

## 元資料

- https://github.com/BoatraceCSV/fun-site/blob/main/docs/web.md
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/development.md
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/architecture.md (2026-07-23、2026-08-12、2026-08-15 の経緯)
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md (§4 ページ表示上のフォールバック)
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/data-sources.md
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/predictors.ts
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/one-mark-distance.ts (`bettingStyleFor` / `bettingBasisFor` / `oneMarkDistanceOptionsFor`)
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/constants/boat-colors.ts
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/astro.config.ts
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/styles/global.css
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/layouts/BaseLayout.astro
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/lib/data.ts
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/race/[date]/[stadiumId]/[raceNumber].astro
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/PredictorCard.astro
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/BettingPicks.astro
- https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/SessionResultsTable.astro
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py

## 演習

1. 公開 CSV `https://boatracecsv.github.io/data/estimate/v1_basic/2026/08/20.csv` と `.../estimate/v10_kimarite/2026/08/20.csv` をダウンロードし、ヘッダ行を比べてください。列名が `N枠_{成分ラベル}` / `N枠_寄与_{成分ラベル}` / `N枠_強さpt` の形になっていること、そして 2 つの予想者で列が完全に一致すること(`componentKeys` が同じ)を確認してください。穴予想が本命予想と違うのは買い目だけで、それは `.../estimate/kimarite/picks/2026/08/20.csv` に `買い目1`〜`買い目5` と `決まり手1`〜`決まり手5` として入っています。`PredictorSpec.bettingStyle: "kimarite"` が指しているのがこのファイルです。
2. (fun-site を clone できる場合)`predictors.ts` の `PREDICTORS` に、`v1_basic` と同じ `componentKeys` を持つ表示専用の予想者を `status: "active"` で 1 つ追加してください。`icon` と `badgeTailwindClass` を他の active と重複しない値にしないと `predictors.test.ts` が落ちること、`pnpm --filter @fun-site/web run dev` でレース詳細ページのカードが 1 枚増えること(フィクスチャ JSON の `predictions[]` にその ID のエントリを足す必要があります)を確認してください。確認できたら、`status: "retired"` にするだけでカードと集計の両方から消えることも試してください。
