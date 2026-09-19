---
title: "買い目の作り方: 強さポイントから 3 連単フォーメーションへ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 点推定(強さpt)を「買う集合」に変換する工程。候補の選定値・許容窓・点数の 3 つが回収率を直接動かすこと、そして「モデルは同じで買い目だけ変えた」実験(v8_aionly)が回収率を有意に下げた事実 |
| システム | 買い目生成をどの層に置くか(boatracecsv ではなく fun-site)、画面に出す買い目と回収率の母数になる買い目を構造的に一致させる設計、予想者ごとの差分をレジストリのフラグで持つ方法 |

第 7 章で、各艇の「強さポイント(強さpt)」を偏差値スケール(平均 50・標準偏差 10)で
得るところまで来ました。しかし強さpt は 6 艇それぞれに付いた 1 つの数値であって、
それ自体は舟券ではありません。3 連単は「1 着・2 着・3 着の艇番を順番どおり当てる」券種なので、
6 つの点推定を「どの出目を何点買うか」という**集合**に変換する工程が必要です。
この工程を boatrace-fun.net では**買い目生成**と呼び、fun-site の
`computeBettingPicks` が担っています。

この章では、その変換ルールを実装から読み取って正確に書き、なぜその形にしたのか、
そしてルールを変えると何が起きるのかを、2026 年 8 月時点の実測値で示します。

## 1. フォーメーションという表現

### 1.1 各着の候補窓の直積

3 連単の買い目を表す方法は 2 つあります。1 つは出目を 1 点ずつ列挙する方法
(`1-3-4`、`1-4-3`、`3-1-4` …)、もう 1 つは**フォーメーション**、すなわち
「1 着候補の集合 × 2 着候補の集合 × 3 着候補の集合」の直積で表す方法です。
たとえば 1 着候補 `{1}`、2 着候補 `{3, 4}`、3 着候補 `{2, 3, 4}` なら、
同じ艇を 2 度使う出目(`1-3-3` など)を除いた `1-3-2`、`1-3-4`、`1-4-2`、`1-4-3` の 4 点になります。

fun-site の既定の予想者(本命予想 `v1_basic` を含む、穴予想以外の全員)はこのフォーメーション形式で
買い目を持ちます。型はこうです。

```ts:packages/shared/src/utils/one-mark-distance.ts
export type FormationPicks = {
  readonly kind: "formation";
  /** 1着候補: 選定値が最大の艇の値 ± tolerance.first 以内 */
  readonly first: readonly number[];
  /** 2着候補: 選定値降順で2位の艇の値 ± tolerance.second 以内 */
  readonly second: readonly number[];
  /** 3着候補: 選定値降順で3位の艇の値 ± tolerance.third 以内 */
  readonly third: readonly number[];
};
```

フォーメーションを選んだ理由は 2 つあります。第一に、強さpt のような**順位付きの点推定**から
機械的に作りやすいことです。「1 着になりそうな艇」「2 着になりそうな艇」を独立に選べば、
あとは直積を取るだけで出目が決まります。第二に、画面での表示が簡潔なことです。
1 着・2 着・3 着の候補艇を 3 つのグループで並べれば、数十点の出目を一覧できます。

![フォーメーションの構造](/images/boatrace-ml-system/08-formation.png)
<!-- 図: 上段に 6 艇の強さpt(または走行距離)を数直線上に並べ、1 位・2 位・3 位の艇を基準に ±窓を帯で描く。中段に 1 着候補 {1}、2 着候補 {3,4}、3 着候補 {2,3,4} の 3 グループ。下段にその直積から同一艇の重複を除いた 4 点(1-3-2 / 1-3-4 / 1-4-2 / 1-4-3)を並べる -->

### 1.2 候補の選び方: 基準艇と許容窓

各着の候補は「**基準艇の選定値 ± 許容窓**」で決めます。実装(`computeBettingPicks`)の規則は次のとおりです。

1. 6 艇を選定値の降順に並べる
2. **1 着候補** = 降順 1 位の艇の値 ± `tolerance.first` 以内にある艇すべて
3. **2 着候補** = 降順 **2 位**の艇の値 ± `tolerance.second` 以内にある艇すべて
4. **3 着候補** = 降順 **3 位**の艇の値 ± `tolerance.third` 以内にある艇すべて

基準が「1 位・2 位・3 位の艇」であって「1 位の艇」ではない点が要です。
2 着候補の基準を 2 位の艇に置くことで、本命が突出しているレースでは 1 着候補が 1 艇に絞られ、
2 着・3 着の窓は 2 番手グループの周りに開きます。逆に上位が拮抗しているレースでは
1 着候補にも 2〜3 艇が入り、点数が自然に増えます。つまり許容窓は
「**上位グループの混戦度に応じて点数を伸縮させる**」働きをしています。

同値の艇が複数いても、基準は「降順で N 番目の艇の値」で取ります(値が同じなら結果も同じです)。
また、境界ちょうどの艇は候補に含めます(`<= tol + 1e-9`。浮動小数点の丸めで境界の艇が落ちないための余裕です)。

許容窓の既定値は**全着順共通で ±0.10** です。

```ts:packages/shared/src/utils/one-mark-distance.ts
export const DEFAULT_BETTING_TOLERANCE: BettingTolerance = {
  first: 0.1,
  second: 0.1,
  third: 0.1,
};
```

着順別に窓を変える仕組み(`BETTING_TOLERANCE_BY_PREDICTOR`)も残っていますが、
2026 年 8 月時点のオーバーライドは**空**です。以前は `v2_tenkai` に
「1 着 ±0.02 / 2 着 ±0.10 / 3 着 ±0.20」(1 着を絞り 3 着を広げる設定)を持たせていましたが、
展開予想の撤去に伴い control と同一レシピに揃えるため 2026-06-13 に削除しました。

### 1.3 選定値は「1 マーク走行距離」

ここまで「選定値」と書いてきたものは、既定では強さpt そのものではなく、
強さpt と予測 ST を合成した **1 マーク走行距離**です。

```ts:packages/shared/src/utils/one-mark-distance.ts
/** 走行距離 = (1 - 予測ST) + 強さpt / 50 - 1.6 */
const distance = 1 - avgST + strengthPt / 50 - 1.6;
```

この式は第 15 章で扱う「1 マーク予想図」(スタート後に各艇が 1 マークまでにどこまで進むか)の
描画に使う量で、買い目の選定にも同じ値を使います。買い目に効くのは艇どうしの**差**だけなので、
定数 `−1.6` は結果に影響しません。効くのは 2 つの項の比率で、`強さpt / 50` という係数は
「強さpt 10 pt の差 = 予測 ST 0.2 秒の差」という重み付けを意味します。
許容窓 ±0.10 は、強さpt だけで言えば ±5.0 pt、ST だけで言えば ±0.10 秒に相当します。

予測 ST は既定で**出走表の全国平均 ST**(race_cards の `艇N_全国平均ST`)です。
第 1 章で述べたとおり、全国平均 ST の `0.00` は「実績なし」の意味なので、
そのまま使うと実績のない新人が「最速スタート」扱いになって走行距離が過大評価されます。
そこで `effectiveAvgST` が `0.00` と未定義を `NO_RECORD_ST_FALLBACK = 0.25` 秒に置き換えます。
この値はスタート予想図の描画と共有しており、片方だけ補完して図と買い目が食い違うことを避けています。

:::message
予測 ST を AI 推定 ST(第 18 章)に差し替える予想者(`useEstimatedST`。`v5_slit` / `v7_aggregate`)も
ありました。差し替えは走行距離を通じて買い目に効くので、回収率 A/B の対象になります。
2026 年 8 月時点で active な予想者にこのフラグを持つものはありません。
:::

### 1.4 デッド候補の除去

3 つの窓を独立に取ると、**どの有効な出目にも登場しない艇**が候補に残ることがあります。
典型は「1 着候補が 1 艇だけで、3 着の窓が広い」ケースです。1 着が常に 1 号艇なら、
1 号艇は 3 着で必ず自分自身と衝突するので、3 着候補に 1 号艇が表示されていても
1 点も買えません。実際に 2026-05-31 の浜名湖 12R で、1 着候補 `[1]` に対して 3 着候補にも 1 号艇が
並ぶ表示が観測されました(前述の着順別窓を使っていた時期の不具合です)。

そこで実装は、3 つの窓を取った後に「1-2-3 着が相異なる有効な出目」を総当たりし、
そこに 1 度でも使われた艇だけを各着に残します。

```ts:packages/shared/src/utils/one-mark-distance.ts
const usedFirst = new Set<number>();
const usedSecond = new Set<number>();
const usedThird = new Set<number>();
for (const a of rawFirst) {
  for (const b of rawSecond) {
    if (a === b) continue;
    for (const c of rawThird) {
      if (c === a || c === b) continue;
      usedFirst.add(a);
      usedSecond.add(b);
      usedThird.add(c);
    }
  }
}
```

除外するのは「どの出目にも使えない艇」だけなので、**買える出目の集合は変わらず、
点数・的中・回収率も不変**です。変わるのは表示だけですが、表示が実際の買い目と一致することは
第 3 節で述べる「画面と集計を食い違わせない」方針の一部です。1 着候補が複数艇ある場合は、
その艇は「別の艇が 1 着になる出目」で 2 着・3 着に使えるので、下位着の候補に残ります。

### 1.5 点数と的中の数え方

フォーメーションの**点数**は、直積から同一艇を 2 度使う組合せを除いた数です
(`countBetCombinations`)。1 点 100 円(`BET_UNIT_YEN`)で買う前提なので、購入額 = 点数 × 100 円です。
**的中**は「1 着の艇番が `first` に、2 着が `second` に、3 着が `third` に含まれること」です(`isBetHit`)。
回収率 = 払戻合計 / 購入額合計、的中率 = 的中レース数 / 母数で、母数は
「結果が確定(1〜3 着が揃い相異なる)し、かつ買い目が組めた(点数 > 0)レース」に限ります。
結果未着・中止・不成立・返還のレースは分子・分母の両方から外します
(返還を「回収率 100%」として計上しないためです。詳しくは第 9 章)。

この規則で control(`v1_basic`)の買い目は**平均 11.5 点**になります
(2026 年 8 月時点、ホールドアウト test 3,532 レース。回収率 86.2%、平均配当 2,166 円)。
1 レース約 1,150 円を投じて、120 通りのうち 1 割弱を押さえる買い方だと言えます。

### 1.6 実例: 距離基準と強さpt 基準で買い目が変わるレース

公開 CSV の 2026-08-01 桐生 2R(レースコード `202608010102`、直前情報反映後の `realtime` 行)を
例にします。強さpt と全国平均 ST から走行距離を計算し、既定の ±0.10 で買い目を組むと
次のようになります。

| 艇番 | 強さpt | 全国平均 ST | 走行距離 |
| --- | ---: | ---: | ---: |
| 1 | 54.42 | 0.18 | 0.308 |
| 2 | 44.30 | 0.21 | 0.076 |
| 3 | 50.79 | 0.19 | 0.226 |
| 4 | 53.27 | 0.16 | 0.305 |
| 5 | 49.16 | 0.15 | 0.233 |
| 6 | 42.57 | 0.19 | 0.061 |

- 走行距離基準 ±0.10: 1 着 `[1, 3, 4, 5]` − 2 着 `[1, 3, 4, 5]` − 3 着 `[1, 3, 4, 5]` = **24 点**
- 強さpt 基準 ±5.0 pt: 1 着 `[1, 3, 4]` − 2 着 `[1, 3, 4, 5]` − 3 着 `[1, 3, 4, 5]` = **18 点**

5 号艇は強さpt では 4 番手(49.16)で 1 着窓(54.42 − 5.0 = 49.42 以上)に届きませんが、
全国平均 ST が 6 艇で最速(0.15)なので走行距離では 3 番手に上がり、1 着候補に入ります。
結果は `4-1-3`(払戻 3,460 円)で、どちらの買い目でも的中でした。
このレースでは「ST を加味するかどうか」が 6 点の差になっています。
ST 項が買い目に与える影響を丸ごと外したらどうなるかを検証したのが、第 4 節の `v8_aionly` です。

## 2. 実装は fun-site 側にある

### 2.1 boatracecsv は強さpt まで、買い目は fun-site

第 0 章の全体図を思い出すと、boatracecsv(Python)は収集・特徴量・強さpt の計算までを担い、
`data/estimate/{predictor_id}/YYYY/MM/DD.csv` に 1 レース 1 行で `N枠_強さpt` を配信します。
買い目はその CSV を読んだ fun-site(TypeScript)のバッチ `prediction-builder.ts` が組みます。
ここに層の境界を置いた理由は次のとおりです。

- **買い目は「予測」ではなく「予測の使い方」**です。強さpt という予測は 1 つでも、
  許容窓や点数の方針はプロダクトの判断で変わり得ます。予測と使い方を別の層に置けば、
  買い目のルールを変えるたびに index CSV を再生成する必要がありません
- **買い目には出走表の情報(全国平均 ST)も要ります**。fun-site は index CSV と出走表
  (race_cards)を同じレースコードで JOIN して `RaceRacer` を組み立てており、
  走行距離の計算に必要な材料が揃うのは fun-site 側です
- **画面が買い目を表示する場所**であり、的中バッジや回収率の集計も fun-site にあります。
  買い目・的中・回収率を同じコードベースの同じ型で扱えば、それらの整合を型で守れます

バッチ側の呼び出しは、予想者ごとにしきい値・予測 ST の種別・選定基準を解決してから
`computeBettingPicks` に渡す形です。

```ts:packages/batch/src/site-builder/prediction-builder.ts
const tolerance = bettingToleranceFor(predictor.id);
const stOptions = oneMarkDistanceOptionsFor(predictor.id);
const basis = bettingBasisFor(predictor.id);
const style = bettingStyleFor(predictor.id);
const ana = style === "formation" ? undefined : anaPicks?.[style];
const dailyPicks =
  style !== "formation"
    ? toComboPicks(ana?.daily)
    : aiEvaluationDaily
      ? computeBettingPicks(
          computeOneMarkDistances(racers, aiEvaluationDaily, stOptions),
          tolerance,
          basis,
        )
      : undefined;
// realtimePicks も同様に aiEvaluationRealtime から組む
const betHitStatus = checkBettingHit(result, dailyPicks, realtimePicks);
const betPayout = computeRaceBetPayoutSummary(dailyPicks, realtimePicks, result, payout);
```

買い目は**当日買い目**(朝バッチ時点の `daily` 評価から)と**直前買い目**(直前情報反映後の
`realtime` 評価から)の 2 種類を組みます。第 1 章で見たとおり `daily` では展示・気象が暫定値なので、
両者は一般に異なります。統計ページや退役判定に使う回収率は**直前買い目のみ**を対象にしています。

### 2.2 例外: 穴予想はフォーメーションで表現できない

穴予想の 2 案(`v9_suji` / `v10_kimarite`。第 21 章)は、この構造の例外です。
たとえばスジ予想の買い目 `3-1-5`、`3-4-5`、`3-5-2` は、どんな候補窓の直積でも作れません
(直積なら `3-1-2` や `3-4-2` も必ず含まれてしまいます)。決まり手モデルは 120 通りの確率の
上位 5 点を取るので、1 レースの 5 点に複数の 1 着艇が混ざることもあります。

そこで買い目の型を直和にし、穴予想は boatracecsv 側で確定させた出目を CSV
(`data/estimate/suji/`、`data/estimate/kimarite/picks/`)で配って、fun-site はそれを読むだけにしました。

```ts:packages/shared/src/utils/one-mark-distance.ts
export type BetCombo = readonly [number, number, number];
export type ComboPicks = {
  readonly kind: "combos";
  readonly combos: readonly BetCombo[];
};
export type BettingPicks = FormationPicks | ComboPicks;
```

`kind` で判別する直和型にしたことで、点数の数え方(`countBetCombinations`)と的中判定(`isBetHit`)は
`kind` で分岐するだけになり、集計・表示の経路は 2 形態で共通です。どちらの CSV を読むかは
`bettingStyleFor(predictorId)` が返す `"suji"` / `"kimarite"` で決まり、それ以外は `"formation"`
として fun-site が計算します。「買い目を上流で確定して配る」設計の詳細は第 21 章で扱います。

## 3. 画面と集計を食い違わせない

### 3.1 予想者の差分はレジストリのフラグで持つ

買い目の作り方が予想者によって違うのは、第 10 章で扱う A/B 実験のためです。
差分は `PredictorSpec` のフラグとして 1 か所に置き、それを 3 つのヘルパーが解決します。

| フラグ | ヘルパー | 決まるもの | 該当する予想者(2026 年 8 月時点) |
| --- | --- | --- | --- |
| `useEstimatedST` | `oneMarkDistanceOptionsFor` | 走行距離の予測 ST(全国平均 ST / AI 推定 ST) | `v5_slit`、`v7_aggregate`、`v8_aionly`(いずれも退役) |
| `strengthOnlyBetting` | `bettingBasisFor` / `bettingToleranceFor` | 選定値(距離 / 強さpt)と窓(±0.10 / ±5.0 pt) | `v8_aionly`(退役) |
| `bettingStyle` | `bettingStyleFor` | フォーメーション計算 / CSV の出目 | `v9_suji`(退役)、`v10_kimarite` |

```ts:packages/shared/src/utils/one-mark-distance.ts
export const bettingBasisFor = (predictorId?: string): BettingBasis =>
  predictorId && predictorById(predictorId)?.strengthOnlyBetting === true ? "strength" : "distance";

export const bettingToleranceFor = (predictorId?: string): BettingTolerance => {
  if (bettingBasisFor(predictorId) === "strength") return STRENGTH_BETTING_TOLERANCE;
  return (predictorId && BETTING_TOLERANCE_BY_PREDICTOR[predictorId]) || DEFAULT_BETTING_TOLERANCE;
};

export const bettingStyleFor = (predictorId?: string): "formation" | "suji" | "kimarite" => {
  const style = predictorId ? predictorById(predictorId)?.bettingStyle : undefined;
  return style === "suji" || style === "kimarite" ? style : "formation";
};
```

未登録の ID や `undefined` を渡しても既定(距離基準・±0.10・フォーメーション)に落ちるので、
呼び出し側は予想者 ID を渡すだけで済みます。

### 3.2 バッチと web の両方が同じヘルパーを通る

問題は、買い目を計算する場所が**2 か所**あることです。バッチ(`prediction-builder.ts`)は
回収率の集計のために買い目を計算し、web(`BettingPicks.astro`)は画面に表示するために
買い目を計算(または受け取り)します。片側だけが `basis` や `stOptions` を渡し忘れると、
「画面に出ている買い目」と「的中率・回収率の母数になった買い目」がずれます。
ずれても例外は出ず、回収率の数字だけが静かに間違うので、発見が難しい種類の不具合です。

対策は 2 段です。まず、web 側も**必ず同じヘルパー**で解決します。

```ts:packages/web/src/components/BettingPicks.astro
const tolerance = bettingToleranceFor(predictorId);
const stOptions = oneMarkDistanceOptionsFor(predictorId);
const basis = bettingBasisFor(predictorId);
const style = bettingStyleFor(predictorId);

const resolvePicks = (
  given: BettingPicks | undefined,
  evaluation: AiEvaluation | undefined,
): BettingPicks | null => {
  if (given) return given;          // バッチが採点した買い目があればそれを描画
  if (!evaluation) return null;
  return computeBettingPicks(computeOneMarkDistances(racers, evaluation, stOptions), tolerance, basis);
};
```

次に、バッチが採点した買い目そのものを `PredictorPrediction.dailyPicks` / `realtimePicks` として
JSON に載せ、web はそれを**描画するだけ**にします(`resolvePicks` の第 1 分岐)。
こうすると画面と集計は同じオブジェクトを見ることになり、構造的に食い違えません。
穴予想は CSV 由来で web から再計算できないため、この経路が必須になります。
web 側の再計算は、買い目が渡されなかった場合のフォールバックとして残っています。

的中判定も同じ考え方で **`isBetHit` の 1 関数に集約**しています。以前は `bet-payout.ts` にも
同じ判定が二重実装されていて、片方だけ直すとずれる状態でした。
判定・点数・回収率が 1 つの `BettingPicks` 値から同じ関数で導かれることが、
第 17 章のダッシュボードが信頼できる前提になっています。

## 4. 選定基準を変えるとどうなるか(v8_aionly)

買い目のルールがどれほど回収率に効くのかを、実験の記録で示します。

`v8_aionly`(AI 予想)は、`v7_aggregate`(統合予想)と**同一のレシピ**
(成分 `course, racer, motor4, exhibit, weather`。index / 強さpt は同値で、boatracecsv 側の計算も同一)で、
fun-site 側の**買い目候補の選定だけ**を差し替えた実験スロットです。
従来の走行距離(予測 ST + 強さpt/50)基準の ±0.10 窓の代わりに、
強さpt のみの ±5.0 pt 窓(等価スケール。ST 項を外した形)で各着の候補を選定します。
「予測 ST が買い目に与える影響を外し、AI の強さ評価だけで買い目を組んだら回収率はどうなるか」を
2026-07-28 から `v7_aggregate` と A/B 比較しました。

```ts:packages/shared/src/predictors.ts
{
  id: "v8_aionly",
  displayName: "AI予想",
  status: "retired",             // 2026-08-09 退役
  startedAt: "2026-07-28",
  componentKeys: ["course", "racer", "motor4", "exhibit", "weather"],
  useEstimatedST: true,          // 図の表示にのみ効く(買い目には影響しない)
  strengthOnlyBetting: true,     // 買い目候補を強さpt ±5.0pt 窓で選定
},
```

結果は、control(`v1_basic`)との同一レース・ペア比較(直前買い目が組めた確定レースのみ、
ペア bootstrap 20,000 反復の 95% CI と並べ替え検定)で次のとおりでした(2026 年 8 月時点、n = 1,892)。

| 項目 | `v8_aionly` | control |
| --- | ---: | ---: |
| 回収率 | 77.30% | 87.92% |
| 差 | **−10.62 pt**(95% CI [−18.5, −2.9]) | |
| p 値 | 0.0001(Holm 補正後 0.0005) | |
| 日次で control 未満だった日数 | **13 / 13 日**(符号検定 p = 0.0002) | |
| 平均点数 | 14.7 点 | 11.7 点 |

差分の大きい上位 20 レースを除外しても差はほぼ変わらず、外れ値依存ではありません。
点数が多いぶん不利なのではないかという疑いに対しては、点数分布を control に揃えて標準化しても
回収率は 76〜78% にとどまったため、**点数ではなく選定そのものの問題**と判断しました。
同日に退役した `v6_course`(−6.91 pt)、`v7_aggregate`(−7.76 pt)と共通する差分は
`waku → course` の成分差し替えで、それが主因である可能性が高いと判断されています。
ただし 3 者は `course` を共有するので独立な検定ではなく、期間も 13〜20 日と短い点は
退役ノートに但し書きとして残されています。3 者の中で差が最も大きかったのが、
買い目の選定まで差し替えた `v8_aionly` でした。
的中率は v6/v7/v8 の 3 者がむしろ高く(46.8〜48.9% 対 46.1〜46.6%)、
「堅い決着は当てるが、安い出目を厚く買って期待値を落とす」負け方に見えます。

この章で強調したいのは、**買い目のルールはモデルと同じくらい回収率に効く**という点です。
強さpt という予測が同じでも、それを集合に変換する規則が違えば、
統計的に有意な差が 2 週間足らずで出ました。予測モデルを改善する前に、
買い目の作り方が固定され、画面と集計で一致していることを確認しておくべき理由がここにあります。
なお、検定の手続きと「同一レースで突き合わせる」ことの意味は第 9 章、
退役の判断とレジストリの運用は第 10 章で扱います。

## 5. 簡略版コード(TypeScript)

実装から本質だけを抜き出したものです。fun-site の `tsconfig`(`strict`、`noUncheckedIndexedAccess`)で
型が通ることを確認しています。関数名・定数名は実装のまま、`expandCombos` だけは
出目リストへの展開を見せるために足しました(実装では点数を数える `countBetCombinations` が同じループを持ちます)。

```ts:betting-picks.ts
/** 買い目候補の選定基準。既定は 1 マーク走行距離、v8_aionly だけ強さpt のみ。 */
export type BettingBasis = "distance" | "strength";
/** 着順別の許容窓(±)。 */
export type BettingTolerance = { readonly first: number; readonly second: number; readonly third: number };
export const DEFAULT_BETTING_TOLERANCE: BettingTolerance = { first: 0.1, second: 0.1, third: 0.1 };
export const STRENGTH_BETTING_TOLERANCE: BettingTolerance = { first: 5.0, second: 5.0, third: 5.0 };
/** 全国平均 ST が 0.00(実績なし)の艇に使う遅めの ST。 */
export const NO_RECORD_ST_FALLBACK = 0.25;

export type OneMarkDistanceEntry = {
  readonly boatNumber: number;
  readonly avgST: number;
  readonly strengthPt: number;
  /** 走行距離 = (1 - 予測ST) + 強さpt / 50 - 1.6 */
  readonly distance: number;
};
export type FormationPicks = {
  readonly kind: "formation";
  readonly first: readonly number[];
  readonly second: readonly number[];
  readonly third: readonly number[];
};
export type BetCombo = readonly [number, number, number];

/** 強さpt と予測 ST から 1 マーク走行距離を全艇分計算する。 */
export const computeOneMarkDistances = (
  racers: readonly { readonly boatNumber: number; readonly nationalAvgST?: number }[],
  strengthPtByBoat: ReadonlyMap<number, number>,
): readonly OneMarkDistanceEntry[] =>
  racers.map((r) => {
    const avgST = r.nationalAvgST || NO_RECORD_ST_FALLBACK; // 0.00 / 未定義 → 補完
    const strengthPt = strengthPtByBoat.get(r.boatNumber) ?? 0;
    const distance = 1 - avgST + strengthPt / 50 - 1.6;
    return { boatNumber: r.boatNumber, avgST, strengthPt, distance };
  });

/** 各着の基準艇 ± 許容窓で候補を取り、有効な出目に 1 つも使われない艇を落とす。 */
export const computeBettingPicks = (
  entries: readonly OneMarkDistanceEntry[],
  tolerance: BettingTolerance = DEFAULT_BETTING_TOLERANCE,
  basis: BettingBasis = "distance",
): FormationPicks => {
  const pickValue = (e: OneMarkDistanceEntry): number =>
    basis === "strength" ? e.strengthPt : e.distance;
  const sortedDesc = [...entries].sort((a, b) => pickValue(b) - pickValue(a));
  const pickWithin = (rank: number, tol: number): readonly number[] => {
    const ref = sortedDesc[rank];
    if (ref === undefined) return [];
    return entries
      .filter((e) => Math.abs(pickValue(e) - pickValue(ref)) <= tol + 1e-9)
      .map((e) => e.boatNumber);
  };
  const rawFirst = pickWithin(0, tolerance.first);
  const rawSecond = pickWithin(1, tolerance.second);
  const rawThird = pickWithin(2, tolerance.third);
  const usedFirst = new Set<number>();
  const usedSecond = new Set<number>();
  const usedThird = new Set<number>();
  for (const a of rawFirst)
    for (const b of rawSecond)
      for (const c of rawThird) {
        if (a === b || b === c || a === c) continue; // 同一艇を 2 度使う出目は存在しない
        usedFirst.add(a); usedSecond.add(b); usedThird.add(c);
      }
  const ascending = (s: ReadonlySet<number>): readonly number[] => [...s].sort((x, y) => x - y);
  return { kind: "formation", first: ascending(usedFirst), second: ascending(usedSecond), third: ascending(usedThird) };
};

/** フォーメーションを出目リストに展開する。`length` が点数(1 点 100 円)。 */
export const expandCombos = (picks: FormationPicks): readonly BetCombo[] => {
  const combos: BetCombo[] = [];
  for (const a of picks.first)
    for (const b of picks.second)
      for (const c of picks.third) if (a !== b && b !== c && a !== c) combos.push([a, b, c]);
  return combos;
};
```

使い方は「強さpt の配列 → 走行距離 → フォーメーション → 出目リスト」の順です。

```ts:example.ts
const racers = [1, 2, 3, 4, 5, 6].map((b, i) => ({
  boatNumber: b,
  nationalAvgST: [0.15, 0.17, 0.16, 0.18, 0.0, 0.19][i],   // 5 号艇は実績なし
}));
const pt = new Map([[1, 62.3], [2, 48.1], [3, 55.7], [4, 52.0], [5, 44.9], [6, 38.0]]);
const picks = computeBettingPicks(computeOneMarkDistances(racers, pt));
// picks: { kind: "formation", first: [1], second: [3, 4], third: [2, 3, 4] }
expandCombos(picks).map((c) => c.join("-"));
// ["1-3-2", "1-3-4", "1-4-2", "1-4-3"]  → 4 点
```

この例では 1 号艇が突出しているので 1 着候補は 1 艇に絞られ、2 着・3 着の窓が
2 番手グループ(3・4 号艇)の周りに開いています。3 着窓には 2 号艇も入りますが、
1 号艇は 1 着に固定されるため 3 着候補には残りません(デッド候補の除去)。

## 元資料

- fun-site [`packages/shared/src/utils/one-mark-distance.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/one-mark-distance.ts) — `computeOneMarkDistances` / `computeBettingPicks` / 各ヘルパーと既定値
- fun-site [`packages/shared/src/utils/bet-hit.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/bet-hit.ts)、[`bet-payout.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/bet-payout.ts) — 的中判定と点数・回収率
- fun-site [`packages/shared/src/predictors.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/predictors.ts) — `PredictorSpec` のフラグと `v8_aionly` のエントリ
- fun-site [`packages/batch/src/site-builder/prediction-builder.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/site-builder/prediction-builder.ts) — バッチ側の買い目生成
- fun-site [`packages/web/src/components/BettingPicks.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/BettingPicks.astro) — web 側の表示
- fun-site [`packages/shared/src/__tests__/one-mark-distance.test.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/__tests__/one-mark-distance.test.ts) — 窓・デッド候補の挙動を固定するテスト
- fun-site [`docs/domain.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md) §1(AI 総合評価、的中率・回収率の母数)・§4(フォールバック)、[`docs/batch.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/batch.md)、[`docs/web.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/web.md)
- boatracecsv [`docs/data/estimate.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) — `v8_aionly` の退役ノートと control の平均点数
- boatracecsv [`docs/data/results.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md)、[`docs/data/programs.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md) — 演習で使う結果・払戻・出走表 CSV の列

## 演習

許容窓を変えると平均点数・的中率・回収率がどう動くかを、公開 CSV だけで計算してみましょう。
使うのは 2026 年 8 月の 1 か月分です。

- `data/estimate/v1_basic/2026/08/DD.csv` — 強さpt(`N枠_強さpt`。`状態=realtime` の行を使う)
- `data/programs/race_cards/2026/08/DD.csv` — 全国平均 ST(`艇N_全国平均ST`。距離基準の再現用)
- `data/results/realtime/2026/08/DD.csv` — 着順(`1着_艇番` 〜 `3着_艇番`)
- `data/results/payouts/2026/08/DD.csv` — 払戻(`3連単_払戻金`)

`computeBettingPicks` を Python に移植し、選定値と窓を切り替えて集計します。
母数は本文どおり「結果が確定し、買い目が組めたレース」です。

```python:tolerance_sweep.py
import io, urllib.request
import pandas as pd

BASE = "https://boatracecsv.github.io/data"
NO_RECORD_ST_FALLBACK = 0.25

def load(path):
    with urllib.request.urlopen(f"{BASE}/{path}") as r:
        return pd.read_csv(io.BytesIO(r.read()), dtype={"レースコード": str})

def compute_betting_picks(values, tol):
    """fun-site computeBettingPicks の移植。values[i] は艇番 i+1 の選定値。"""
    boats = list(range(1, len(values) + 1))
    desc = sorted(boats, key=lambda b: -values[b - 1])
    within = lambda ref: [b for b in boats if abs(values[b - 1] - values[ref - 1]) <= tol + 1e-9]
    raw = [within(desc[0]), within(desc[1]), within(desc[2])]
    used = [set(), set(), set()]
    for a in raw[0]:
        for b in raw[1]:
            for c in raw[2]:
                if a != b and b != c and a != c:
                    used[0].add(a); used[1].add(b); used[2].add(c)
    return [sorted(s) for s in used]

def count_combos(p):
    return sum(1 for a in p[0] for b in p[1] if a != b for c in p[2] if c not in (a, b))

def is_hit(p, top3):
    return top3[0] in p[0] and top3[1] in p[1] and top3[2] in p[2]

rows = []
for day in range(1, 32):
    try:
        idx = load(f"estimate/v1_basic/2026/08/{day:02d}.csv")
        cards = load(f"programs/race_cards/2026/08/{day:02d}.csv")
        res = load(f"results/realtime/2026/08/{day:02d}.csv")
        pay = load(f"results/payouts/2026/08/{day:02d}.csv")
    except Exception:
        continue                       # 開催なし / 未生成の日は飛ばす
    idx = idx[idx["状態"] == "realtime"]
    df = (idx.merge(cards[["レースコード"] + [f"艇{i}_全国平均ST" for i in range(1, 7)]], on="レースコード")
             .merge(res[["レースコード", "1着_艇番", "2着_艇番", "3着_艇番"]].dropna(), on="レースコード")
             .merge(pay[["レースコード", "3連単_払戻金"]], on="レースコード"))
    for _, r in df.iterrows():
        top3 = tuple(int(r[f"{k}着_艇番"]) for k in (1, 2, 3))
        if len(set(top3)) < 3:
            continue                   # isSettledResult
        pt = [float(r[f"{i}枠_強さpt"]) for i in range(1, 7)]
        if any(pd.isna(pt)):
            continue
        st = [float(r[f"艇{i}_全国平均ST"]) or NO_RECORD_ST_FALLBACK for i in range(1, 7)]
        dist = [1 - s + p / 50 - 1.6 for s, p in zip(st, pt)]
        rows.append((pt, dist, top3, int(r["3連単_払戻金"])))

print(f"n={len(rows)}")
configs = [("距離 ±0.10 (control)", "dist", 0.10)] + [(f"強さpt ±{t}", "pt", t) for t in (3, 5, 8)]
for label, basis, tol in configs:
    n = bets = hits = cost = payout = 0
    for pt, dist, top3, sanrentan in rows:
        picks = compute_betting_picks(pt if basis == "pt" else dist, tol)
        k = count_combos(picks)
        if k == 0:
            continue
        n += 1; bets += k; cost += k * 100
        if is_hit(picks, top3):
            hits += 1; payout += sanrentan
    print(f"{label:22s} 平均 {bets / n:5.2f} 点  的中率 {100 * hits / n:5.1f}%  回収率 {100 * payout / cost:5.1f}%")
```

筆者の実行結果(2026 年 8 月、n = 4,449 レース)は次のとおりです。

| 選定基準 | 平均点数 | 的中率 | 回収率 |
| --- | ---: | ---: | ---: |
| 走行距離 ±0.10(control の再現) | 11.65 | 45.2% | 81.4% |
| 強さpt ±3.0 | 5.59 | 29.3% | 81.8% |
| 強さpt ±5.0 | 12.39 | 46.8% | 80.6% |
| 強さpt ±8.0 | 31.22 | 70.4% | 77.5% |

確認してほしいことは 3 つあります。

1. 走行距離 ±0.10 の再現が平均 11.65 点になり、本文の「control は平均 11.5〜11.7 点」と
   整合すること。公開 CSV と本章の規則だけで、サイトの買い目が再現できています
2. 窓を広げると的中率は単調に上がる(29% → 47% → 70%)のに、回収率は下がること。
   窓を広げて増える出目は「選定値が下位の艇を含む出目」で、当たっても薄い配当を厚く買うことになります。
   的中率だけを目標にすると回収率を落とす、という第 1 章の指摘をここで数値として確かめられます
3. 強さpt ±5.0 は走行距離 ±0.10 と等価スケールですが、平均点数がやや多く(12.39 対 11.65)、
   回収率はわずかに低い(80.6% 対 81.4%)こと。この 1 か月・1 予想者の差は小さく、
   これだけで優劣は言えません。第 4 節の `v8_aionly` は同一レースでのペア比較と検定を経て
   「有意に低い」と判断した点が違います(その手続きは第 9 章)

発展課題として、`daily` 行(当日買い目)で同じ集計をして直前情報の寄与を見ること、
着順別に窓を変えて(例: 1 着 ±0.05 / 3 着 ±0.15)点数と回収率の動きを見ることを勧めます。
