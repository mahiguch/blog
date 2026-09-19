---
title: "説明可能性: 寄与の分解と検算ページ"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 線形モデルの寄与分解を UI まで貫く。「成分pt → 寄与 → 強さpt」の各段を実値で見せ、再現できない成分は「再現できる材料」を上流に出させる |
| システム | 検算ページの設計(一致したときだけ「一致」と言う)、Python 実装を TypeScript に移植するときの罠の一覧、移植の検証粒度と許容誤差の決め方 |

第 7 章で作った強さpt は、成分ごとの偏差値pt に場別の重みを掛けて足しただけの線形モデルです。線形であることの最大の利点は、予想の根拠を成分ごとに分解して人に見せられることにあります。この章では、fun-site がその分解をどこまで画面に出しているか、Python で計算された値を TypeScript で再計算するときに何が合わなかったか、そして「fun-site 側では原理的に計算できない成分」をどう扱ったかを説明します。

章の主題は最後の点です。再現できない成分を「再現不可」と表示して終わらせるのではなく、**再現に必要な材料を上流(BoatraceCSV)に配ってもらう**形に持ち込みました。上流と下流の間の交渉そのものが設計になっている、という話です。

## 1. 寄与の積み上げ棒

レース詳細ページの予想者カードには「AI 評価の内訳」として、枠 1〜6 の横棒があります。1 本の棒は成分ごとの寄与pt を積み上げたもので、棒の長さが強さpt に相当します。

![AI 評価の内訳(積み上げ棒)と凡例リンク](/images/boatrace-ml-system/16-ai-evaluation-chart.png)
<!-- 図: レース詳細ページ「AI 評価の内訳」のスクリーンショット(realtime 評価のもの)。枠 1〜6 の横棒が 枠番 / 選手 / モーター / 展示 / 気象 の 5 色で積み上がり、各セグメントに寄与pt の数字、右端に合計(強さpt)。凡例の各項目の右に ▸ が付き、リンクになっていることが分かるようにする -->

描画は `AiEvaluationChart.astro` が担当します。設計上の要点は 3 つです。

**成分の並びは予想者の `componentKeys` で決まる。** 第 14 章で見た `PredictorSpec` の `componentKeys` をそのまま順序として使い、成分名や色は `COMPONENT_SHORT_LABELS` / `COMPONENT_COLORS` の辞書から引きます。成分を足した予想者を投入しても、このコンポーネントは変更が要りません。

**`state=daily` では preview 由来の成分を隠す。** 展示pt と気象pt は直前情報が入るまで中立値 50 で、寄与は 0 に潰されています(第 4 章)。朝の評価で「展示 0.0pt」と描くと「展示が悪かった」と読まれるので、`isPreviewDerivedComponent(key)` が true の成分は daily のときセグメントも凡例も出しません。

```ts:AiEvaluationChart.astro(抜粋)
const isDaily = evaluation.state === "daily";
const segmentKeys: readonly ComponentKey[] = evaluation.componentKeys.filter(
  (key) => !(isDaily && isPreviewDerivedComponent(key)),
);
```

**凡例が検算ページへの入口になる。** `racerPtHref` / `motorPtHref` / `wakuPtHref` / `exhibitPtHref` / `weatherPtHref` の各 prop を渡すと、凡例の「選手」「モーター」「枠番」「展示」「気象」がそれぞれの詳細ページへのリンクになります。prop が無ければただのラベルなので、アーカイブなど根拠ページを生成しない文脈でも同じコンポーネントを使えます。退役した `v4_motor` 系の成分 `motor4` は `motor` と同じリンク先を共有しますが、`v6_course` 系の `course` にはリンクを付けていません。`course` のテーブルは「場 × レース番号 × コース」で、枠番pt の「場 × 季節 × コース」と軸が違い、枠番詳細ページの解説が当てはまらないためです。

もう 1 つ細かい点として、棒に積むのは `Math.max(0, 寄与)` です。重みが非負制約付きで学習されている(第 7 章)ので寄与が負になることは通常ありませんが、欠損補完などで 0 になった成分はセグメント幅 0 として省略します。

## 2. 5 つの検算ページ

凡例から飛ぶ先は、レース単位の 5 ページです。URL は `/race/{YYYY-MM-DD}/{場コード}/{レース番号}/` の下に成分名を付けた形になっています。

| パス | 成分 | ページが「実値で展開する」もの |
| --- | --- | --- |
| `lanes/` | 枠番pt | その場のコース強度テーブル(4 季節 × 6 コース)→ テーブル値 → z → 枠番pt → 寄与 |
| `racers/` | 選手pt | 全国 5 節 + 当地 5 節の着順列 → 着順ごとの適用スコア → 素点 → 選手pt → 寄与 |
| `exhibition/` | 展示pt | 展示タイム + オリジナル展示のレース内偏差値 → 等重み平均 → z → 展示pt → 寄与 |
| `weather/` | 気象pt | 6 特徴量 × コース別係数の表 → 有利pt 変動 → z → 気象pt → 寄与 |
| `motors/` | モーターpt | 直近 6 節の走(生得点・セル μ/σ・残差 z・減衰重み)→ 加重平均 → 収縮 → 素点 → モーターpt → 寄与 |

どのページも構成は同じで、6 艇の比較表 → 艇ごとのカード → 末尾に計算ロジックの折りたたみ解説、と並びます。カードの中身が「式」ではなく「この艇の実値を式に当てはめた結果」になっているのが、ここで言う検算ページです。たとえば気象詳細ページの係数テーブルは、行が回帰の 6 特徴量と当日の値、列が進入コース 1〜6 で、セルには `当日の値 × 係数` が入り、その下に合計(有利pt 変動)・気象pt・寄与の行が付きます。読者は自分で足し算をして確かめられます。

### 「一致したときだけ一致と言う」

検算ページで再計算した値と、index CSV に入っている表示値は、原理的には同じ式なので一致するはずです。しかし過去日のページを再ビルドすると、当時の index CSV を作った後にテーブルや重みが月次で更新されていて、0.1pt 程度ずれることがあります。ずれたまま「= 枠番pt」と書くと嘘になります。

そこで各カードは、再現値と表示値を比較し、**一致したときだけ見出しに「(表示値と一致)」を出し、ずれたときは両方の値を並べて注記する**ようにしました。判定のしきい値は成分によって少しずつ違います。

| 成分 | 判定 | 理由 |
| --- | --- | --- |
| 枠番pt | `\|再現値 − 表示値\| < 0.05` | テーブル値も μ/σ/w も月次で動くため、やや広め(`WakuPtCard.astro`) |
| 気象pt / 展示pt | `< 0.005`(小数第 2 位まで一致) | 上流が出力時に `round(x, 2)` するので、正しく再現できていれば 2 桁で一致する(`weatherPtMatchesIndex` / `exhibitPtMatchesIndex`) |
| モーターpt | `< 0.005 + (10 ÷ σ) × 5e-7` | 素点の入力自体が上流 CSV で小数 6 桁に丸められているため、その誤差が偏差値変換で 10/σ 倍される分を許容する(`motorPtMatchesIndex`。§3 で説明) |

このため「一致」の表示は、テーブルの状態を保証する検算そのものになっています。なお、ビルド時点のテーブル・重みは `wakuPtBasis` / `weatherPtBasis` / `exhibitPtBasis` / `motorPtBasis` としてレース JSON に焼き込んであります。後日ビルドし直しても当時の値で検算できるようにするためです(第 13 章)。

## 3. 再現できない成分をどうするか

5 成分のうち、fun-site 側でどこまで再現できるかは成分ごとに違います。2026-08-23 時点の整理は次のとおりです。

![成分ごとの再現可否と材料の出どころ](/images/boatrace-ml-system/16-reproducibility-map.png)
<!-- 図: 5 成分を行にした表図。列は「生値の材料」「μ/σ/w の出どころ」「fun-site で再現できる段階」「照合結果」。枠番: win_rate.csv + weights → 生値から全段 / 1,782 エントリ一致。選手: recent_national + recent_local → 素点まで(μ/σ/w 未取り込み) / 素点は照合対象外。展示: previews(tkz, original_exhibition) + weights → 生値から全段 / 49,092 艇一致。気象: previews/sui + sui_params + weights → 生値から全段 / 7,996 エントリ中 1 件不一致。モーター: estimate/motor_pt/{runs,motors,baseline} を上流が配る → 素点は上流の明細、偏差値化以降を fun-site / 933 セル一致(境界 2 件)。矢印で「上流が配る」ものを強調する -->

| 成分 | 生値の材料 | fun-site で計算する範囲 | 照合(2026 年 8 月時点) |
| --- | --- | --- | --- |
| 枠番pt | `estimate/stadium/win_rate.csv`(場 × 季節 × コース)と weights の μ/σ/w | 生値から寄与まで全段 | 2026-08-22 の全 1,782 エントリで `N枠_枠番pt` / `N枠_寄与_枠番pt` と小数第 2 位まで一致 |
| 選手pt | `programs/recent_national` / `recent_local` の着順列 | 素点まで。μ/σ/w は取り込んでいないので、選手pt と寄与は index CSV の値を表示し、w は `寄与 ÷ 選手pt` で逆算 | (素点は index CSV に無いので照合対象外) |
| 展示pt | `previews/tkz` + `previews/original_exhibition`(レース内で閉じる)と weights の μ/σ/w | 生値から寄与まで全段 | 2026-07〜08 の 49,092 艇で小数第 2 位まで完全一致 |
| 気象pt | `previews/sui` + `estimate/stadium/sui_params.csv` と weights の μ/σ/w | 生値から寄与まで全段 | 2026-08 の 8 日ぶん 7,996 エントリを小数第 2 位まで照合し、不一致は 4 桁丸めの境界に当たった 1 件のみ |
| モーターpt | 当場の直近 6 節の全走 + 全 24 場横断のコース補正ベースライン | **素点は計算できない。** 上流が配る明細を表示し、素点から先の偏差値化と寄与だけを計算 | 2026-08-22 の 933 セルで小数第 2 位まで一致(6 桁丸めの境界をまたいだ 2 件を除く) |

照合の数値は fun-site `docs/domain.md` と `docs/architecture.md` の記録から引いています。母数の単位が「エントリ」「艇」「セル」と揃っていないのは、成分ごとに検証した単位が違うためで、どれも「index CSV の 1 枠 1 成分ぶんの値」を数えたものです。

### 展示pt: 上流を変えずに済んだ例

展示pt は 2026-08-23 まで「再現不可」と表示していました。展示走行のどの計測値をどう重み付けしているかが上流の実装で、fun-site は重みを持っていないと考えていたためです。ところが第 4 章で見たとおり、展示pt の生値は「展示タイム + オリジナル展示 1〜3 をレース内で偏差値化して等重み平均」で、**項目別の重みは存在しません**。外から要るのは場別の μ/σ/w だけで、それは既に取得していた weights CSV に `mu_exhibit` / `sigma_exhibit` / `w_exhibit` として入っていました。

結果として上流の配信物は一切変えず、batch の `fetchStadiumTables` が切り出す成分を `waku` / `weather` の 2 つから `exhibit` を足した 3 つに増やし、`exhibitPtBasis` としてレース JSON に焼き込むだけで済みました。「再現できない」は思い込みで、実装を読み直したら材料は揃っていた、という例です。

### モーターpt: 上流に明細を配ってもらった例

モーターpt はそうはいきませんでした。第 5 章の素点は

```
素点 = n_eff / (n_eff + k) × Σ(w × z) / Σw        k = 10
  z  = (生得点 − μ_セル) / σ_セル                  セル = 級別 × グレード分類 × 進入
  w  = exp(−ln2 / 60 × 経過日数)                   半減期 60 日
```

で決まり、セルの μ/σ は**全 24 場を横断したコーパス**から作られます。1 基ぶんの素点でも全場の履歴に依存するので、当日ぶんの CSV しか取得しない fun-site では、当場の 6 節ぶんの出走表を全部揃えても原理的に計算できません。

ここで取った選択が、上流(BoatraceCSV)に**計算過程そのものを明細として配ってもらう**ことでした。上流の `build_index.py` は素点を計算する時点でこれらをメモリ上に持っているので、`motor_pt_breakdown.py` がそれをそのまま 3 種の CSV に書き出します。

| ファイル | 粒度 | 内容 |
| --- | --- | --- |
| `estimate/motor_pt/runs/YYYY/MM/DD.csv` | 1 走 1 行 | 生得点・セル μ/σ・残差 z・減衰重み。集計対象外の走(F / L / 失 / 妨 / 欠 / 不)は行として現れない |
| `estimate/motor_pt/motors/YYYY/MM/DD.csv` | 1 モーター 1 行 | Σw / Σw² / n_eff / 加重平均残差 / 素点。走が 1 本も無いモーターも 1 行出す |
| `estimate/motor_pt/baseline/YYYY/MM/DD.csv` | コース補正セル | 級別 × グレード分類 × 進入の μ/σ/サンプル数。絞り込み前の全場コーパスから算出した値そのもの |

対象はその日の `race_cards` に出てくるモーターだけに絞ります。2026-08-22(13 場開催)の実測で 567 基 / 19,470 走 / 約 1.8MB でした。`motors` に「走が無いモーターも 1 行出す」のは、下流が「ファイルに無い」と「履歴が無い」を区別できるようにするためです。fun-site 側は前者を `motorPtHistory` が undefined、後者を `runs` が空で `rawPt` が null として画面に分けて出します。

この関係は、選手pt に対する `recent_national` / `recent_local` と同じです。上流は「値」だけでなく「値を作った材料」を配り、下流はそれを使って計算過程を開示します。`baseline` を fun-site が読むのは、実は計算に必要だからではありません(`runs` の `セルμ` / `セルσ` は既に解決済みの値です)。モーター詳細ページに「このレースの 6 基が引いたセルの μ/σ/サンプル数」を折りたたみで置き、**素点を fun-site で計算できない理由の実物**として見せるためです。

トレードオフはページの重さです。`runs` は 1 レースあたり 230 走前後になるので、モーター単位で一定の 3 列(記録日・場コード・モーター番号)を落とした `MotorPtHistoryRun` に詰め替えてからレース JSON に載せています。それでも整形済みのレース JSON は 74KB から 183KB に太りました(2026-08-23)。「なぜ 6 節ぶんの走行履歴をページごとに持つのか」と問われたら、答えは「素点の根拠を実値で見せるため」です。

もう 1 つのトレードオフが、§2 の表に出てきた許容幅です。`motors` の `素点` は小数 6 桁に丸められて配られます。偏差値変換 `50 + 10 × (素点 − μ) ÷ σ` で 10/σ(おおむね 50〜80 倍)に拡大されるので、上流が内部の float から出した値とは最大で `10/σ × 5e-7` ずれます。これが 2 桁表示の丸め境界をまたぐと、中身は同じなのに 0.01 だけ違って見えます。2026-08-22 の 933 セルではこれが 2 件ありました。`motorPtMatchesIndex` が σ を受け取って許容幅を広げているのはこのためで、本当に内訳や重みが差し替わった場合の差はこれよりずっと大きいので、誤報の心配はありません。

## 4. Python → TypeScript 移植の罠

枠番・選手・展示・気象の 4 成分は fun-site で再計算します。同じ式を書き写すだけのはずが、index CSV と一致させるまでにいくつかの挙動を「合わせる」必要がありました。第 4 章で個別に触れたものも含め、一覧にします。

| 対象 | 上流(Python)の挙動 | 移植で合わせたこと | 合わせないとどうなるか |
| --- | --- | --- | --- |
| 選手pt の素点 | `round(total_score / total_runs)` は**偶数丸め**(round half to even) | `roundHalfToEven()` を自前で書く | `Math.round` は half up なので、56.5 のようなケースで素点が 1pt ずれる |
| 選手pt の入力 | 全国 5 節と当地 5 節を**重複排除せずに連結**して `racer_pt_for_boat()` に渡す。当地で走った節は 2 回計上される | 同じ順序(全国 前1〜5節 → 当地 前1〜5節)で連結し、**重複排除しない**。どの節が二重かは `duplicated` フラグで開示 | 重複排除すると素点が一致しない |
| 選手pt の `[F]` | `parse_finishes()` は優勝戦の括弧内から**着順の数字だけ**を拾う。`[F]` `[妨]` は得点にも出走回数にも入らない | 括弧内の非着順トークンは読み捨てる(bare な `F` は 0 点で出走 1 回) | `[F]` を bare の `F` と同じ扱いにすると分母が 1 増える |
| 選手pt の欠損 | 有効な出走が無い選手は 50 ではなく **30** で補完(`COMPONENT_MISSING_FALLBACK`) | 素点が null の艇は「30 で補完される」と表示 | 他の成分と同じ 50 だと思って説明すると食い違う |
| 展示pt の偏差値 | `hensachi()` の標準偏差は `std(ddof=0)`(母標準偏差)。符号は `(mean − v)`(小さいほど速い)。有効値 2 艇未満は NaN、`std == 0` は 50 | `raceHensachi()` を同じ規約で書く | pandas 既定の `ddof=1` で書くと小数第 2 位が合わない |
| 展示pt の生値 | 特徴量列に載せる時点で `round(v, 2)` | `Number(x.toFixed(2))` で丸めてから偏差値に載せる | 丸めないと展示pt が最大 0.01 ずれる |
| 気象pt の生値 | 特徴量列に載せる時点で `round(v, 4)` | `Number(x.toFixed(4))` で丸めてから偏差値に載せる | 丸めないと気象pt が 0.01 ずれる。`Math.round(x * 1e4) / 1e4` だと二進の誤差で境界がずれる |
| 気象pt の風向 | 風向が空欄のレースは風向コード 1(北)で埋める | 追い風 / 向かい風とも 0 に倒す(あえて合わせていない) | そのレースだけ再現値がずれうる。ページは「両方の値を並べる」動作になる |
| 出力の丸め | 成分pt は `round(pt, 2)`、寄与は `round(w × 丸める前の pt, 2)`、強さpt は `round(Σ 丸める前の寄与, 2)` | 同じ順序で丸める | CSV の `展示pt × w` を手計算しても寄与の最下位桁が合わない |

### 偶数丸め

Python の組み込み `round()` は、ちょうど .5 のとき偶数側に丸めます。JavaScript の `Math.round` は常に大きい側です。実際に並べると次のようになります(この章の執筆時に Python 3 と Node で確認したものです)。

| 入力 | Python `round()` | JS `Math.round` |
| --- | --- | --- |
| 0.5 | 0 | 1 |
| 2.5 | 2 | 3 |
| 56.5 | 56 | 57 |
| 57.5 | 58 | 58 |
| −1.5 | −2 | −1 |
| −2.5 | −2 | −2 |

素点は「着順スコアの合計 ÷ 出走回数」で、たとえば 20 走で合計 1,130 点なら 56.5 です。ここで 57 と出すと、選手詳細ページに書く素点が index CSV の選手pt を説明できなくなります。

### `toFixed` と `x * 1e4`

気象pt の生値を 4 桁に丸めるとき、素朴に `Math.round(x * 1e4) / 1e4` と書くと、`x * 1e4` の掛け算で二進の誤差が乗ります。0.00035 は二進では 0.00035 よりわずかに小さい値ですが、`0.00035 * 1e4` はちょうど 3.5 になり、`Math.round` で 4 に切り上がります。Python の `round(0.00035, 4)` は二進表現そのものを見て 0.0003 を返し、`(0.00035).toFixed(4)` も `"0.0003"` を返します。`toFixed` は掛け算を挟まず二進表現を直接 10 進に展開して丸めるので、こちらが Python に近い動作です。

ただし `toFixed` と Python の `round(x, 4)` も完全には同じではありません。二進で厳密に表せる .5 の値(たとえば 1/32 = 0.03125)では、Python は偶数丸めで 0.0312、`toFixed(4)` は half up で 0.0313 を返します。気象pt の 7,996 エントリ中 1 件の不一致が「4 桁丸めの境界」で起きたことは記録されていますが、それがこの種の値だったかどうかまでは確認していません。一致しなかった 1 件を追い切るより、「境界ではずれうる」と割り切ってページ側で両方の値を出す方が、検算ページの目的には合っていると考えられます。

### 簡略版コード

選手pt の素点を再現する部分を、`racer-pt.ts` から本質だけ抜き出したものです。関数名と定数名は実装のものを保っています。

```ts:racer-pt.ts(簡略版)
/** 着順スコア表 [バケット][優勝戦か][着順-1]。index_features.py の SCORE_TABLE と同値 */
export const RACER_PT_SCORE_TABLE = {
  SG_GI: { yusho: [100, 98, 94, 91, 88, 85], other: [85, 82, 77, 73, 69, 65] },
  GII: { yusho: [80, 78, 74, 71, 68, 65], other: [70, 67, 62, 58, 54, 50] },
  GIII: { yusho: [65, 63, 59, 55, 52, 50], other: [60, 58, 55, 50, 46, 45] },
} as const;
type RacerPtGradeBucket = keyof typeof RACER_PT_SCORE_TABLE;

/** 選手責任(F / L / 失 / 妨)。0 点だが出走回数には計上する */
const RACER_RESPONSIBLE_TOKENS: ReadonlySet<string> = new Set(["F", "L", "失", "妨"]);

/** 偶数丸め。Python の round() と同じ。Math.round(56.5) は 57 だが Python は 56 */
export const roundHalfToEven = (value: number): number => {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
};

const racerPtGradeBucket = (grade: string): RacerPtGradeBucket =>
  /ＳＧ|SG|ＰＧ|PG|ＧⅠ|GⅠ|G1|Ｇ１/.test(grade) ? "SG_GI"
  : /ＧⅡ|GⅡ|G2|Ｇ２/.test(grade) ? "GII"
  : "GIII";

/** 全角 ０-９ / 半角 0-9 を数値に。数字でなければ null */
const toDigit = (ch: string): number | null => {
  const c = ch.codePointAt(0) ?? -1;
  if (c >= 0xff10 && c <= 0xff19) return c - 0xff10;
  if (c >= 0x30 && c <= 0x39) return c - 0x30;
  return null;
};

export type RacerPtSessionInput = { readonly grade: string; readonly ranks: string };

/**
 * 素点 = round(Σ 着順スコア ÷ 出走回数)。
 * sessions は上流と同じ順(全国 前1〜5節 → 当地 前1〜5節)で、重複排除せずに渡す。
 */
export const computeRacerBasePoint = (sessions: readonly RacerPtSessionInput[]): number | null => {
  let totalScore = 0;
  let totalRuns = 0;
  for (const { grade, ranks } of sessions) {
    const table = RACER_PT_SCORE_TABLE[racerPtGradeBucket(grade)];
    const chars = [...ranks];
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i] ?? "";
      if (ch === "[" || ch === "［") {
        // 優勝戦。括弧内の「着順の数字だけ」を拾うので [F] [妨] は何も計上しない
        const close = chars.findIndex((c, j) => j > i && (c === "]" || c === "］"));
        if (close === -1) continue;
        for (const c of chars.slice(i + 1, close)) {
          const d = toDigit(c);
          if (d !== null && d >= 1 && d <= 6) { totalScore += table.yusho[d - 1] ?? 0; totalRuns += 1; }
        }
        i = close;
        continue;
      }
      const d = toDigit(ch);
      if (d !== null) {
        if (d >= 1 && d <= 6) { totalScore += table.other[d - 1] ?? 0; totalRuns += 1; }
        continue;
      }
      const token = ch === "Ｆ" ? "F" : ch === "Ｌ" ? "L" : ch;
      if (RACER_RESPONSIBLE_TOKENS.has(token)) totalRuns += 1;
      // 欠 / 転 / 落 / 沈 / エ / 不 と日区切りの空白は、分子・分母とも計上しない
    }
  }
  return totalRuns === 0 ? null : roundHalfToEven(totalScore / totalRuns);
};
```

実装ではこれに加えて、節ごと・トークンごとの内訳(`RacerPtMark`)と、全国側と当地側の両方に現れた節を示す `duplicated` フラグを返します。選手詳細ページはそれを使って、着順チップの下に適用スコアを併記し、F / L / 失 / 妨 は赤で `0`、欠 / 転 / 落 / 沈 / エ / 不 は灰で `除外`、二重計上された節には「二重計上」バッジを付けます。上流の挙動を隠さずそのまま見せる、という方針です。

呼び出し側は `recentForm.national` と `recentForm.local` をこの順で連結して渡すだけです。

```ts
const basePoint = computeRacerBasePoint([...recentForm.national, ...recentForm.local]);
```

### 検証の粒度

移植の正しさをどう確かめるかも設計の一部です。fun-site が取った粒度は「index CSV の値と小数第 2 位まで、実データの全件で照合する」でした。展示pt なら 2026-07〜08 の 49,092 艇、気象pt なら 2026-08 の 8 日ぶん 7,996 エントリです。単体テストのゴールデンだけでは、上の表にある `[F]` や風向空欄のような、実データにしか現れないケースを拾えません。逆に全件照合だけだと回帰を検知できないので、代表レースを固定したゴールデンテストと組み合わせています。

不一致が出たら、それを「バグ」と「境界」に分けます。境界(丸め幅の半分以下の差)は許容幅に折り込み、それ以外は原因を突き止めて表に一行足す。上の表はそうやって増えてきました。

## 5. 何を出さないか

説明可能性は「出せるものを全部出す」ことではありません。枠番詳細ページには、**選手個人の枠番別過去 10 走をあえて出していません**。

枠番pt は「場 × 季節 × コース」のテーブルを引いた値で、選手個人を一切見ていません。同じ場・同じ季節・同じコースなら、誰が乗っていても同じ値です。枠番詳細ページはそのことを本文で説明しています。その説明の直下に「この選手はこの枠で直近 10 走どうだったか」という個人成績を並べると、読み手は「枠番pt にこの成績が入っているのだろう」と混同します。`programs/waku10` から作る枠番別過去 10 走の集計(`computeWaku10Aggregate()`)は枠番pt の入力ではなく参考値なので、表示はレース詳細ページの枠番別過去 10 走セクション(`#waku10`)に一本化し、枠番詳細ページからは「選手個人の枠番成績はこちら」とリンクするだけにしました。

同じ理由で、モーター詳細ページに出す出走表の 2 連率・3 連率と `motorStats` の期成績には「どちらもモーターpt の入力ではない」と明記し、展示詳細ページに出す展示 ST・体重・チルトにも「展示pt の入力ではない」と添えています。数字を並べる場所が、その数字の意味を決めてしまうためです。

## 元資料

- fun-site [`docs/domain.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md) §1 AI 総合評価(成分ごとの再現可否、移植で合わせる挙動の一覧)
- fun-site [`docs/architecture.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/architecture.md)(2026-08-23 の展示pt 再現対応、モーターpt 明細対応)
- fun-site [`docs/web.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/web.md)(5 つの検算ページと各カードの仕様)、[`docs/data-sources.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/data-sources.md)(取り込む CSV と静的テーブル)
- fun-site [`packages/web/src/components/AiEvaluationChart.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/AiEvaluationChart.astro)
- fun-site 検算ページ [`lanes.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/race/[date]/[stadiumId]/[raceNumber]/lanes.astro) / [`racers.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/race/[date]/[stadiumId]/[raceNumber]/racers.astro) / [`exhibition.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/race/[date]/[stadiumId]/[raceNumber]/exhibition.astro) / [`weather.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/race/[date]/[stadiumId]/[raceNumber]/weather.astro) / [`motors.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/pages/race/[date]/[stadiumId]/[raceNumber]/motors.astro)
- fun-site カード [`WakuPtCard.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/WakuPtCard.astro) / [`RacerPtCard.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/RacerPtCard.astro) / [`ExhibitPtCard.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/ExhibitPtCard.astro) / [`WeatherPtCard.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/WeatherPtCard.astro) / [`MotorPtCard.astro`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/MotorPtCard.astro)
- fun-site 再現計算 [`racer-pt.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/racer-pt.ts) / [`rank-marks.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/rank-marks.ts) / [`waku-pt.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/waku-pt.ts) / [`exhibit-pt.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/exhibit-pt.ts) / [`weather-pt.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/weather-pt.ts) / [`motor-pt.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/motor-pt.ts)、欠損補完値 [`predictors.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/predictors.ts)
- boatracecsv [`docs/data/motor_pt.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_pt.md)(モーターpt 素点の明細)、[`docs/data/estimate.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md)(補完ルール、展示pt の算出手順)
- boatracecsv [`scripts/boatrace/motor_pt_breakdown.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/motor_pt_breakdown.py) / [`scripts/build_motor_pt_breakdown.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_motor_pt_breakdown.py)
- boatracecsv [`scripts/boatrace/index_features.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/index_features.py)(`parse_finishes()` / `racer_pt_for_boat()` / `hensachi()` と 4 桁・2 桁丸め)、[`scripts/build_index.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_index.py)(出力時の丸め順序)、[`scripts/boatrace/predictors/registry.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py)(`COMPONENT_MISSING_FALLBACK`)

## 演習

1. Python の `round()` と JavaScript の `Math.round` で結果が異なる入力を 5 つ見つけてください。正の値だけでなく負の値も含めると、どちらの方向にずれるかが見えます。次に、その 5 つすべてで Python と同じ値を返す `roundHalfToEven` を TypeScript で実装してください(この章の簡略版コードは見ずに書いてから比べることを勧めます)。
2. `Number(x.toFixed(4))` と `Math.round(x * 1e4) / 1e4` の結果が異なる `x` を 1 つ見つけ、Python の `round(x, 4)` がどちらと一致するか確かめてください。
3. 公開 CSV `https://boatracecsv.github.io/data/programs/recent_national/YYYY/MM/DD.csv` と `programs/recent_local/YYYY/MM/DD.csv` から任意のレースの 1 枠ぶんを取り、`computeRacerBasePoint` で素点を計算してください。全国側と当地側の両方に同じ節(場名と期間が一致)が現れる選手を探し、重複排除した場合としない場合で素点がいくつ変わるかを比べてください。
