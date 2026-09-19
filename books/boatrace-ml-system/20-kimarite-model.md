---
title: "穴予想(1): 荒れ度メーターと決まり手モデル"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | favourite-longshot bias(人気薄ほど回収率が下がる構造)、多クラス分類での多項ロジスティック回帰 vs 勾配ブースティング、クラス集合の凍結、「校正は良いのに argmax は使えない」という非対称、abstain(棄権)が逆効果になる理由、表示粒度によって情報量が変わること |
| システム | 月次学習 → 係数 CSV → 日次・直前推論という分業、推論側を sklearn 非依存にする理由、スキーマ不整合で「黙って落ちる」設計、予想者に紐づかない独立指標の置き場、校正モニタリングの月次集計 |

この章と次の第 21 章は、設計書 `docs/design/ana_prediction.md`(約 79KB)を 2 つに分けたものです。この章は「決まり手モデル」そのものと、その最初の商品である荒れ度メーターを扱います。モデルの出力から買い目を合成し、強さポイントとブレンドし、A/B で判定する部分は第 21 章で扱います。数値はすべて 2026 年 8 月時点の設計書と実装ドキュメントに記載されたものです。

## 1. 穴は構造的に不利

穴予想を作る前に、穴がどれだけ不利かを測っておく必要があります。「毎レース人気 k 位の 3 連単を 1 点買う」戦略の回収率を、`data/results/payouts/`(2025-11-01〜2026-08-11、n=42,090 レース)で集計した結果です。

| 人気帯 | 点数 | 的中率 | 回収率 |
| --- | ---: | ---: | ---: |
| 1〜3 位 | 3 | 26.4% | 76.8% |
| 4〜10 位 | 7 | 28.6% | 77.9% |
| 11〜20 位 | 10 | 17.7% | 73.7% |
| 21〜40 位 | 20 | 15.1% | 69.2% |
| 41〜80 位 | 40 | 10.0% | 60.8% |
| 81〜120 位 | 40 | 2.3% | **43.6%** |

控除率 25% はどの帯でも同じなので、本来はどの帯を買っても回収率は 75% 前後になるはずです。実際には人気 1〜3 位の 76.8% に対し、81〜120 位は 43.6% まで落ちます。これは投票者が人気薄を買いすぎているぶんの損で、競馬などでも知られる favourite-longshot bias がそのまま出ています。**穴に寄ること自体が回収率にマイナス**であり、大穴を選別しても勝てません。狙うとすれば中穴(2,000〜30,000 円)に絞る必要があります。

それでも穴を扱う理由は、配当の分布にあります。同じ 42,090 レースで 3 連単の配当帯ごとに「レースの割合」と「払戻総額に占める割合」を見ると、両者が大きくずれています。

| 3 連単 配当 | レース割合 | 払戻総額に占める割合 |
| --- | ---: | ---: |
| 〜1,000 円 | 19.2% | 1.9% |
| 1,000〜3,000 円 | 36.9% | 9.3% |
| 3,000〜10,000 円 | 27.5% | 21.1% |
| 10,000〜30,000 円 | 11.7% | 27.3% |
| 30,000〜100,000 円 | 4.0% | 27.0% |
| 100,000 円〜 | 0.6% | 13.3% |

**1 万円以上の配当はレースの 16.3% にすぎませんが、払戻総額の 67.6% を占めます。** 本命予想だけを出していると、払戻の 2/3 が発生する領域を最初から捨てていることになります。回収率 100% 超えは狙わず、「本命とは別の生成原理で、配当の大きい側を扱う予想者」を置く価値はここにあります。

## 2. 現行モデルは「荒れるか」を持っていない

第 7 章の強さポイント(`v1_basic`)は「誰が強いか」を測る指標です。では「レースが荒れるか」も測れているのでしょうか。`1 枠の強さ pt − 他 5 艇の最大強さ pt` で 5 分位に分け、1 号艇の 1 着率と万舟率(3 連単 1 万円以上)を集計しました(n=14,333 レース、`estimate/v1_basic` がある 2026-05 以降)。

| 分位 | 1 号艇 1 着率 | 万舟率 | 1 着が 4〜6 号艇 |
| ---: | ---: | ---: | ---: |
| 1(拮抗) | 35.0% | 17.9% | 24.7% |
| 3 | 56.5% | 17.3% | 17.9% |
| 5(1 号艇圧倒) | 73.2% | 14.3% | 13.1% |

1 号艇の勝敗は 35% ⇔ 73% とよく分かれるのに、万舟率は 17.9% ⇔ 14.3% しか動きません。「誰が強いか」と「どう決まるか」は別の軸で、現行の 5 成分は後者を持っていないということです。この穴を埋める指標を作ることが、穴の買い目を出すより先に価値があると判断しました。

## 3. 決まり手を軸にする

### 3.1 決まり手は穴そのもの

ボートレースの公式結果には「決まり手」(逃げ・差し・まくり・まくり差し・抜き・恵まれ)が記録されています(第 1 章)。決まり手別に配当を集計すると(n=42,010 レース)、逃げか否かで配当が 4〜6 倍違います。

| 決まり手 | 割合 | 平均配当 | 中央値 | 万舟率 | 平均人気 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 逃げ | 52.5% | 2,565 円 | 1,430 円 | 3.6% | 8.1 |
| 差し | 11.9% | 10,569 円 | 4,790 円 | 26.9% | 25.0 |
| まくり | 15.6% | 12,374 円 | 6,170 円 | 33.4% | 28.9 |
| まくり差し | 11.8% | 14,728 円 | 6,500 円 | 36.7% | 31.2 |
| 抜き | 6.2% | 10,689 円 | 3,730 円 | 24.3% | 22.9 |
| 恵まれ | 0.7% | 10,657 円 | 2,470 円 | 20.4% | 18.7 |

つまり「逃げ以外を当てる」ことと「穴を当てる」ことはほぼ同義で、予測ターゲットと穴の定義が一致します。着順を直接予測するのではなく、決まり手を予測ターゲットに据える理由はこれです。

### 3.2 セル = 決まり手 × 1 着コース

決まり手だけでは着順に結び付きません。そこで「決まり手 × 1 着コース」の組み合わせを 1 クラス(セル)として多クラス分類にします。「逃げは 1 コースからしか出ない」「まくり差しは 2 コースからは出ない」といった制約が、セルの有無として自然に入ります。

観測数 n が 60 未満のセルは受け皿の `その他_{1 着コース}` に畳みます。設計時の学習窓(約 7,000 レース)では 28 クラスでしたが、実装時に全履歴(41,740 レース)で判定し直すと `逃げ_2`(n=188)、`抜き_6`(122)、`差し_6`(104)、`恵まれ_2〜5`(60〜71)も閾値を超え、**26 セル + `その他` 6 個 = 32 クラス**になりました。`逃げ_2` という一見ありえない組み合わせが出るのは、1 着コースを展示進入(`previews/stt`)基準で取っているためです。展示と本番で進入が変わるレースが 12% ほどあり、その場合に定義どおり発生します。

このクラス一覧は `scripts/boatrace/kimarite.py` の `CELLS` に**定数として凍結**しています。月次再学習のたびに閾値を評価し直すとクラスが増減し、係数 CSV のスキーマが変わってしまうからです。設計レビュー(H1)ではクラス集合を全期間で決めていた点が「test へのリーク」と指摘されましたが、実測では train 期間で凍結しても log-loss 差は 0.0007 nat(誤差)でした。リークの実害はなかったものの、運用上は凍結が必須という結論です。

```python:scripts/boatrace/kimarite.py(抜粋)
CELLS: tuple[str, ...] = (
    "その他_1", "その他_2", "その他_3", "その他_4", "その他_5", "その他_6",
    "まくり_2", "まくり_3", "まくり_4", "まくり_5", "まくり_6",
    "まくり差し_3", "まくり差し_4", "まくり差し_5", "まくり差し_6",
    "差し_2", "差し_3", "差し_4", "差し_5", "差し_6",
    "抜き_1", "抜き_2", "抜き_3", "抜き_4", "抜き_5", "抜き_6",
    "恵まれ_2", "恵まれ_3", "恵まれ_4", "恵まれ_5",
    "逃げ_1", "逃げ_2",
)
CELL_INDEX = {c: i for i, c in enumerate(CELLS)}
NIGE_CELL = "逃げ_1"

def cell_of(kimarite: str, first_course: int) -> str:
    """(決まり手, 1着コース) → 凍結クラス名。一覧に無ければ その他_{コース}。"""
    raw = f"{kimarite}_{first_course}"
    return raw if raw in CELL_INDEX else f"その他_{first_course}"
```

なお `results/realtime` の決まり手は「逃　げ」「差　し」「抜　き」のように全角スペース入りで記録されているので、`KIMARITE_MAP` で正規化してから `cell_of` に渡します。

### 3.3 特徴量は「進入コース順」に並べる

特徴量の要点は、艇を枠番順ではなく**進入コース順に並べ替える**ことです。決まり手は「何コースの艇がどう動いたか」の話なので、「3 コースに入った艇の全国勝率」という位置ベースの列にしないと線形モデルが構造を拾えません。

| 出典 | 特徴量 | 状態 |
| --- | --- | --- |
| `programs/race_cards` | 級別・F 本数・全国勝率・当地勝率・全国 2 連対率・モーター 2 連対率・ボート 2 連対率・全国平均 ST(各 6 スロット) | daily / realtime |
| `previews/stt` | スタート展示 ST(6)、枠なりか、前付け艇数 | realtime |
| `previews/tkz` | 展示タイム・チルト(各 6) | realtime |
| `previews/sui` | 風速・波高・気温・水温、風向の sin/cos、天候の one-hot | realtime |
| レースコード | レース回、場コードの one-hot(24) | daily / realtime |

進入コースの定義は「展示進入(`previews/stt`)」に統一しています(レビュー H2)。設計時の集計表は結果の実進入で作っていたのでモデルと定義がずれていましたが、賭け時点で使えるのは展示進入だけです。実進入との 1 着コース一致率は 96.8%(枠なりレース 98.4%、前付けありレース 88.0%)で、ターゲットを展示進入基準にしたときの Stage1 の情報利得(ベースレート比の log-loss 改善)は +0.1809 nat、実進入基準では +0.1541 nat でした。実進入基準は絶対値の log-loss こそ低いのですが、ベースレートも低い(分布が集中している)ため、モデルが稼いでいる情報量は展示進入基準のほうが大きいという結果です。

朝の時点では展示進入がないので、`状態=daily` 用のモデルは `race_cards` だけを使い、艇を枠番順に並べます。`状態=realtime` 用は展示進入順に並べ替えて preview と気象を足します。特徴量セットが違うので係数も 2 本持ちます。「preview が必須だから朝は出せない」と当初は考えていましたが、実測では daily 版でも realtime 版の情報利得の 79% が取れました(test log-loss 1.8586 vs 1.8201、ベースレート比 +0.1423 nat vs +0.1809 nat)。枠なり率が 85.3% あるため、枠なり仮定のコストが小さいのが効いています。

### 3.4 多項ロジスティック回帰 vs 勾配ブースティング

Stage1(セル多クラス予測)のモデルは、同じ特徴量・同じ分割で比較して多項ロジスティック回帰(L2 正則化、`C = 0.006` を valid で選択)を採りました。設計時の分割は学習 2026-05-01〜06-24(6,956 レース)/ 検証 06-25〜07-17(3,689)/ テスト 07-18〜08-11(3,527)です。

| Stage1 モデル | valid log-loss | test log-loss | ベースレート比 改善 |
| --- | ---: | ---: | ---: |
| ベースレート(定数) | 1.9983 | 1.9874 | — |
| HistGradientBoosting | 1.9665 | 1.9456 | 0.042 nat |
| **多項ロジスティック回帰(C=0.006)** | **1.8465** | **1.8306** | **0.157 nat** |

GBM が負けた理由は、学習データが 7,000 レース × 25 クラス(設計時)しかなく過学習するためだと考えられます。もう 1 つの理由はシステム側にあります。回帰係数は CSV に落とせるので、第 7 章の `weights` や `course_win_rate.csv` と同じ「学習済みテーブルを月次で再生成してコミットする」運用にそのまま乗ります。GBM のモデルファイルを配る運用は新しく作らねばならず、その分の価値が実測で出ていませんでした。

### 3.5 one-hot の判定が反転した話

場コード(1〜24)・風向・天候を数値のまま線形モデルに入れるのは、本来は順序を仮定してしまうので不適切です(レビュー M3)。設計時に one-hot 化 + 風向の sin/cos を試したところ、7,000 レースでは効きませんでした。しかし学習窓を全履歴に伸ばして 31,000 レースにすると、判定が反転しました。

| 構成 | 学習データ | valid | test |
| --- | ---: | ---: | ---: |
| 数値のまま | 7,000 | 1.8465 | 1.8306 |
| one-hot 場/天候 + 風向 sin/cos | 7,000 | 1.8513 | 1.8334 |
| 数値のまま | 31,000 | 1.8342 | 1.8201 |
| **one-hot 場/天候 + 風向 sin/cos** | **31,000** | **1.8301** | **1.8132** |

7,000 レースでは `C = 0.006` の強い正則化で場の次元がほとんど使われず、one-hot にしても差が出ません。データが増えると正則化を緩められるようになり、場ごとの差が使えるようになって −0.007 nat 効くようになりました。「エンコーディングを直すより学習データを増やせ」という診断が先にあり、増やした結果としてエンコーディングも効くようになった、という順序です。

学習窓を伸ばせるのは、index 由来の特徴量(強さ pt など 36 列)を落としても test log-loss が 1.8306 → 1.8489 としか悪化しないためです。index 系を外せば `estimate/v1_basic` が始まる 2026-05 ではなく、`results/realtime` が始まる 2025-11 から学習できます。実際に train の開始日を振った結果、全履歴(30,865 レース)で test 1.8201、2026-05 開始(7,639 レース)で 1.8558 と単調に改善し、古いデータで劣化する兆候はありませんでした。したがって **Stage1 は 6 か月ローリングではなく全履歴で学習**します(レビュー M2)。

### 3.6 欠損補完と、死に特徴量のバグ

レビュー(M1)では「全場共通の median 補完は無意味」と指摘されましたが、実測では現行が最良でした。

| 補完方式 | valid | test |
| --- | ---: | ---: |
| **全体 median(現行)** | **1.8342** | **1.8201** |
| 場別 median + 欠損フラグ | 1.8365 | 1.8240 |
| レース内 z 化 | 1.8471 | 1.8308 |

指摘の前提が違っていました。欠損はほとんど起きません(ボート 2 連対率 3.14%、モーター 2 連対率 2.89%、展示タイム 1.29%、スタート展示 ST 0.01%、何か 1 つでも欠損があるレースは 5.22%)。「preview 欠損が本番で常時起きる」という想定が誤りだったので、補完方式を凝る価値はありません。

ただしこの検証の副産物として 1 件のバグが見つかりました。検証コードで `race_cards` の体重列名を取り違えており、体重 6 列が **100% 欠損の死に特徴量**になっていたのです。100% 欠損の列は median 補完で定数になり、標準化で 0 になるので、学習は何事もなく通ります。エラーにならないぶん気づきにくいバグです。実装の `kimarite.py` では `PREVIEW_FEATURES` を スタート展示・展示タイム・チルト の 3 つにして、体重は特徴量から外しています。

:::message
「欠損率を測る」という地味な検証が、指摘の妥当性を判断すると同時にバグを見つけました。特徴量を足すときは、少なくとも 1 度は列ごとの欠損率と分散を出しておくべきです。第 12 章の不変条件チェックと同じ発想です。
:::

## 4. 校正は良いが argmax は使えない

Stage1 の出力の使い方を決めたのがこの節の実測です。まず確率としての性能を見ます。実装後のホールドアウト(全履歴 41,740 レースの末尾 20%)では次の値でした。

| モデル | log-loss | ベースレート | 改善 | P(逃げ_1) 予測平均 / 実測 |
| --- | ---: | ---: | ---: | --- |
| realtime | 1.8331 | 2.0107 | **+0.1776 nat** | 0.518 / 0.521 |
| daily | 1.8734 | 2.0107 | +0.1373 nat | 0.528 / 0.521 |

P(逃げ_1) の予測平均 0.518 に対して実測 0.521 で、ずれは 0.3pt です。設計時の test(3,527 レース)で予測帯ごとに見ても、8 帯中 7 帯が ±3pt 以内、最大で −6.6pt でした。

| P(逃げ) 予測帯 | n | 予測平均 | 実測 | 差 |
| --- | ---: | ---: | ---: | ---: |
| 0.0–0.2 | 167 | 15.6% | 15.0% | −0.6pt |
| 0.2–0.3 | 320 | 25.7% | 27.5% | +1.8pt |
| 0.3–0.4 | 423 | 35.1% | 31.4% | −3.7pt |
| 0.4–0.5 | 526 | 45.1% | 38.4% | −6.6pt |
| 0.5–0.6 | 609 | 55.0% | 57.0% | +2.0pt |
| 0.6–0.7 | 671 | 65.0% | 67.4% | +2.4pt |
| 0.7–0.8 | 596 | 74.8% | 71.8% | −3.0pt |
| 0.8–1.0 | 215 | 83.4% | 80.9% | −2.4pt |

![P(逃げ) の予測帯別 校正プロット](/images/boatrace-ml-system/kimarite-calibration.png)
<!-- 図: 横軸に予測帯の予測平均(15.6〜83.4%)、縦軸に実測率を打ち、対角線と重ねる。各点に n を添える。0.4–0.5 帯の −6.6pt が最大のずれとして目立つ程度で、他は対角線に近いことを示す -->

一方、同じモデルの argmax(最も確率の高いセルを 1 つ選ぶ)は使い物になりませんでした。

| 指標 | 実測(test 3,527 レース) |
| --- | ---: |
| top-1 セル的中率 | **52.3%** |
| 「常に 逃げ_1 と言う」ベースライン | **52.4%** |
| top-2 セルに正解が入る率 | 62.3% |

top-1 に選ばれたセルの内訳は、逃げ_1 が 3,332 レース(**94.5%**)、差し_2 が 71、まくり_2 が 66、まくり_3 が 42 と続きます。モデルの argmax は「常にイン逃げ」と言うのに勝てていないのです。

この 2 つは矛盾していません。逃げ_1 が 52% を占める分布では、どのレースでも P(逃げ_1) が他のどのセルより大きくなりやすく、argmax はほぼ常に逃げ_1 になります。しかし P(逃げ_1) の値そのものは 15% から 83% まで幅広く動いていて、その値は実測とよく一致しています。**確率としては情報があるのに、最頻クラスとしては情報がない**という状況です。多クラス分類で 1 クラスが過半を占めるとき、精度(accuracy)で評価するとこの情報が見えなくなります。log-loss で評価していたから気づけました。

設計レビューでは、この点が Blocking(B1)として挙がりました。当初の出力案は「セル確率の上位 3〜4 件を『3 コースがまくる』という文で表示し、1 着≠1 コースの買い目を添える」形でした。94.5% のレースで主予測が「1 コースがそのまま逃げる 68%」になり、その下に「1 着が 1 コース以外」の買い目が並ぶことになります。予想者が自分の主予測を否定する買い目を出す状態で、これでは出せません。

採った解は「何が起きるかを宣言するのをやめ、当たる要素だけを表示する」ことです。**荒れ度メーターは `1 − P(逃げ_1)` だけを見せ、決まり手の argmax は出しません。** 穴予想は定義上「本命が来ない側」に賭けるものなので、「イン逃げ 68% 濃厚。穴予想は残り 32% に賭ける」と立場を明示すれば、荒れ度と 1 着≠1 の買い目は両立します(買い目側は第 21 章)。

## 5. 表示粒度で情報量が変わる

argmax がだめでも、表示の形を変えれば決まり手を出せるのではないか、と考えて測り直したのがこの節です。結果は「出せる形と出せない形がはっきり分かれる」でした。

まずレース単位です。実際に荒れた(1 着≠1 コース)test の 1,598 レースについて、表示候補ごとの的中率を「同じことを常に言うベースライン」と比べます。

| 表示候補 | 的中率 | ベースライン | 差 |
| --- | ---: | ---: | ---: |
| セル(決まり手 × 1 着コース)top1 | 21.7% | 18.0% | +3.7pt |
| **決まり手のみ(コース無視)** | **33.7%** | **33.7%** | **±0.0pt** |
| **1 着コースのみ(決まり手無視)** | **45.1%** | **30.1%** | **+15.0pt** |

決まり手はレース単位では当てられていません。「常にまくりと言う」のと同じ 33.7% です。1 着コースを与えた条件下でも、コース別の最頻決まり手というベースレートに対して加重平均で −1.1pt(3,527 レース)でした。一方「荒れるなら何コース頭か」は +15pt 効いています。当てられているのは決まり手ではなくコースなので、展開の文言はコース主体で書き、決まり手はモデルの内部構造として使います。

次に買い目 1 点ごとの注釈です。「3-1-4 は 3 コースのまくり差しの形」のように、出目に決まり手を添える形を測りました。的中した買い目 437 点で、注釈の決まり手が実際の決まり手と一致した率です。

| 注釈の作り方 | 一致率 |
| --- | ---: |
| 1 着コース別の最頻決まり手(コースしか見ない) | 48.7% |
| **出目(3 コースの並び)別の最頻決まり手 — 静的テーブル** | **63.2%** |
| モデルの P(セル \| その出目) の最有力セル | 60.6% |

こちらは +14.5pt の情報があります。理由は、決まり手を特定しているのが事前情報ではなく「2 着・3 着の並び」だからです。1 コースが 2 着に残っていればまくり差し、外が続いていればまくり、というように出目の形そのものが決まり手を語っています。

そして重要なのは、**この注釈にモデルは要らない**という点です。出目 → 最頻決まり手の静的テーブル(120 行)が、モデルの P(セル | 出目)と同等以上でした(63.2% vs 60.6%、n=437 なので差は誤差の範囲)。したがって決まり手注釈は決まり手モデルの差別化要素ではなく、スジ予想(第 21 章)を含む穴予想共通の表示レイヤーとして実装しています。

まとめると、同じ「決まり手」でも表示粒度で可否が変わります。

| 表示 | 可否 | 根拠 |
| --- | --- | --- |
| 荒れ度 `1 − P(逃げ_1)` | ○ | 校正誤差 概ね ±3pt |
| 「荒れるなら何コース頭か」 | ○ | 45.1% 対 30.1% |
| 買い目 1 点ごとの決まり手注釈 | ○ | 63.2% 対 48.7%(静的テーブルで足りる) |
| 決まり手の確率分布(全種類を並べる) | ○ | 決まり手別の予測平均と実測のずれ −1.2〜+2.3pt |
| 「このレースは○○が決まる」(argmax) | × | 条件付きでもベースレート −1.1pt |

fun-site の荒れ度メーターは、この表のうち荒れ度だけを出しています。決まり手の内訳は出しません。

## 6. abstain は効かない

B1 の当初の解決案は abstain(棄権)でした。「荒れそうなレースだけ買う」ために `P(逃げ_1) ≤ しきい値` のレースに絞れば、主予測と買い目の矛盾も消えるはずだ、という案です。設計レビューでも H4 として「全レースで必ず 5 点買う設計は、P(逃げ)=85% のレースでも穴を買うことになり、意図的な負け筋だ」と指摘されていました。

valid(3,689 レース)で実測すると、しきい値を厳しくするほど回収率は下がる一方でした(買い目は 1 着≠1 の top5、第 21 章)。

| abstain しきい値 | 発火率 | 回収率 | 平均配当 |
| --- | ---: | ---: | ---: |
| なし | 100.0% | **79.6%** | **3,438 円** |
| P(逃げ) ≤ 0.70 | 80.6% | 73.9% | 2,989 円 |
| P(逃げ) ≤ 0.60 | 61.3% | 76.4% | 2,841 円 |
| P(逃げ) ≤ 0.50 | 44.0% | 74.5% | 2,685 円 |
| P(逃げ) ≤ 0.40 | 28.1% | 65.6% | 2,392 円 |

理由は平均配当の列に出ています。**「予測しやすく荒れるレース」は配当も安い**のです。モデルが荒れると分かるレースは市場も荒れると分かっているので、絞るほど妙味が消えます。第 1 節の favourite-longshot bias が別の形で現れたものです。レビューの High 指摘(H4)のほうが誤りで、全レース発火のまま据え置きました。

さらに、abstain では矛盾自体も解けませんでした。しきい値を厳しくしても、発火したレースの top-1 セルは依然として大半が逃げ_1 のままです(しきい値なしで 94.5%、≤ 0.35 まで絞っても 72.1%)。矛盾を消すには、表示の設計を変えるしかなかったということです。

:::message alert
レビュー指摘の一部(H4・M1・M3)は、実測すると「指摘が誤り」「指摘が過大」「データ量次第で反転」でした。指摘をそのまま実装するのではなく、まず測る、というのがこの設計書を通じた教訓です。逆に H1(クラス凍結)のように、実害はゼロでも運用上必須という判断もあります。
:::

## 7. 実装

### 7.1 月次学習 → 係数 CSV → 日次・直前推論

荒れ度メーターは予想者に紐づかない独立の指標なので、`ACTIVE_PREDICTORS`(第 10 章)とは無関係に毎回動きます。ジョブの分担は第 11 章の Cloud Run Jobs にそのまま相乗りしています。

| ジョブ | 処理 | 出力 |
| --- | --- | --- |
| monthly-weights(毎月 1 日) | `build_kimarite.py`(全履歴で再学習) | `data/estimate/kimarite/tables/cell_coef_{daily,realtime}.csv` |
| monthly-weights | `build_kimarite_calibration.py`(校正監視) | `data/estimate/kimarite/tables/calibration.csv` |
| daily-sync(朝) | `build_kimarite_probs.py --mode daily` | `data/estimate/kimarite/YYYY/MM/DD.csv` |
| preview-realtime(2 分毎) | `build_kimarite_probs.write_day(..., "realtime")` を内部呼び出し | 同上(realtime 行を upsert) |

![荒れ度メーターのデータフロー](/images/boatrace-ml-system/kimarite-pipeline.png)
<!-- 図: 左に results/realtime × previews × race_cards(全履歴)→ monthly-weights の build_kimarite.py → cell_coef_daily.csv / cell_coef_realtime.csv(係数 CSV、git commit)。右に daily-sync / preview-realtime が build_kimarite_probs.py で係数 CSV を読み、kimarite/YYYY/MM/DD.csv(荒れ度 + P_セル × 32)を書く。さらに fun-site batch が読んで UpsetMeter.astro で表示、月次で build_kimarite_calibration.py が results と突き合わせて calibration.csv、という流れ -->

係数 CSV は 1 行 = 1 クラスで、先頭 3 行に補完値(`median`)と標準化パラメータ(`center` / `scale`)を置きます。

| 行種別 | 内容 |
| --- | --- |
| `median` | 欠損補完値(全体中央値) |
| `center` / `scale` | 標準化パラメータ |
| `coef` × 32 | クラスごとの切片と係数 |

学習と推論を分けている理由は 2 つあります。1 つは、推論を sklearn 非依存にしておくと、2 分毎の直前バッチでモデルを読み込む必要がなく、係数 CSV さえあれば動くことです。もう 1 つは、係数のクラス構成が `boatrace.kimarite.CELLS` とずれていたら**黙って動かずに落ちる**ようにするためです。古い係数で推論して静かに壊れる(第 12 章)のを、スキーマチェックで防ぎます。特徴量の作り方は `kimarite.py` の `build_features` を学習と推論で共有し、列順は `feature_names(state)` で固定して、係数 CSV のヘッダと突き合わせます。

静的テーブルの置き場が `tables/` サブディレクトリなのは、日次 CSV と同階層に置くと Cloud Run の cone-mode sparse-checkout が日次ファイルの全履歴まで checkout してしまうためです。なお「全履歴で再学習」は cone の広さ次第で、2026-08-22 までは monthly-weights の sparse-checkout に `race_cards` / `previews` が 8 か月分しかなく、実際の学習母数は 43,595 → 30,160 レース(31% 欠落)になっていました。`build_kimarite.py` は `race_cards` のない日を無言でスキップするからです。ジョブログの `races=NNNNN (開始日 〜 終了日)` の開始日が `results/realtime` の最古日と一致するかで再発を検知しています(第 12 章)。

### 7.2 学習(簡略版)

実装 `scripts/build_kimarite.py` の `fit` と `write_coefficients` から本質だけを抜いたものです。median 補完 → 標準化 → 多項ロジスティック回帰、の順です。train に出なかったクラスの切片を −30 にしているのは、32 クラスの形を必ず揃えつつ、そのクラスの確率をほぼ 0 にするためです。

```python:build_kimarite_min.py
import csv
from pathlib import Path
import numpy as np
from kimarite import CELLS  # 凍結した 32 クラス

C_REGULARIZATION = 0.006  # valid で選択した L2 の強さ

def fit(X: np.ndarray, y: np.ndarray):
    """median 補完 → 標準化 → 多項ロジスティック回帰。(mu, center, scale, W, b)。"""
    from sklearn.linear_model import LogisticRegression

    mu = np.nanmedian(X, axis=0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    Xf = np.where(np.isfinite(X), X, mu)
    center, scale = Xf.mean(axis=0), Xf.std(axis=0)
    scale = np.where(scale > 1e-9, scale, 1.0)  # 定数列は 0 のまま
    model = LogisticRegression(C=C_REGULARIZATION, max_iter=4000)
    model.fit((Xf - center) / scale, y)
    W = np.zeros((len(CELLS), X.shape[1]))
    b = np.full(len(CELLS), -30.0)  # train に出なかったクラスは確率ほぼ 0
    for i, cls in enumerate(model.classes_):
        W[cls], b[cls] = model.coef_[i], model.intercept_[i]
    return mu, center, scale, W, b

def write_coefficients(path: Path, names: list[str], mu, center, scale, W, b) -> None:
    """1 行 = 1 クラス。先頭 3 行に補完値・標準化パラメータを置く。"""
    rows = [["median", "", ""] + list(mu), ["center", "", ""] + list(center),
            ["scale", "", ""] + list(scale)]
    rows += [["coef", cls, b[i]] + list(W[i]) for i, cls in enumerate(CELLS)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["行種別", "クラス", "切片"] + names)
        w.writerows([[f"{v:.6g}" if isinstance(v, float) else v for v in r] for r in rows])
```

`LogisticRegression` は既定のソルバー(lbfgs)で多クラスのラベルを渡すと、one-vs-rest ではなく多項(softmax)ロジスティック回帰として学習します。`C` は正則化の逆数で、小さいほど強い正則化です。`C = 0.006` はかなり強く、3.5 節で見たとおり 7,000 レース規模では場の one-hot がほぼ潰されるほどです。

### 7.3 推論(簡略版)

実装 `scripts/build_kimarite_probs.py` の `CellModel` に対応します。sklearn を import せず、係数 CSV だけで softmax を計算します。`load` で `CELLS` との整合を検査するのがこの設計の要です。

```python:build_kimarite_probs_min.py
import csv
import math
from pathlib import Path
from kimarite import CELLS

class CellModel:
    def __init__(self, median, center, scale, intercept, weights, names):
        self.median, self.center, self.scale = median, center, scale
        self.intercept, self.weights, self.names = intercept, weights, names

    @classmethod
    def load(cls, path: Path) -> "CellModel":
        params: dict[str, list[float]] = {}
        classes, intercept, weights = [], [], []
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            names = next(reader)[3:]
            for kind, cls_name, b, *vals in reader:
                vals = [float(v) for v in vals]
                if kind == "coef":
                    classes.append(cls_name); intercept.append(float(b)); weights.append(vals)
                else:
                    params[kind] = vals
        if tuple(classes) != CELLS:  # 古い係数で静かに壊れるのを防ぐ
            raise ValueError(f"{path}: クラス構成が CELLS と一致しません")
        return cls(params["median"], params["center"], params["scale"],
                   intercept, weights, names)

    def predict(self, x: list[float]) -> list[float]:
        z = [((v if math.isfinite(v) else m) - c) / s
             for v, m, c, s in zip(x, self.median, self.center, self.scale)]
        logits = [b + sum(w_i * z_i for w_i, z_i in zip(w, z))
                  for b, w in zip(self.intercept, self.weights)]
        hi = max(logits)  # オーバーフロー防止に最大値を引く
        exps = [math.exp(v - hi) for v in logits]
        return [e / sum(exps) for e in exps]
```

推論の呼び出し側は、1 レースごとに `build_features` → `predict` を回し、`荒れ度 = 1 − p[CELLS.index("逃げ_1")]` と 32 個の確率を書きます。確率は小数 6 桁で書いています。4 桁に丸めると 32 クラスの合計が 1 から 0.2% ずれ、下流の log-loss 集計(第 21 章)に効くためです。実装ではさらに `model.names` が `feature_names(state)` と一致するかも検査し、`write_day` が `状態` ごとに行を upsert して、daily 行を保ったまま realtime 行を差し替えます。

### 7.4 合成データでの動作確認

上の 2 つを合成データ(20,000 レース、12 特徴量、2% の欠損、逃げ_1 が基本で x0 が大きいほど まくり_3 が増える構造)でつないで確認した結果です。

```text
classes in train: 32 / 32
sum of probs: 1.000000 .. 1.000000
P(逃げ_1) 予測平均 0.332 / 実測 0.324
log-loss 2.7228 vs base 2.8051 (改善 0.0823 nat)
top-1 が 逃げ_1 の割合: 90.8%
OK: 不整合を検出 → cell_coef_bad.csv: クラス構成が CELLS と一致しません
```

合成データでも「P(逃げ_1) の平均は実測に合う」「log-loss はベースレートより良い」「それでも argmax はほぼ逃げ_1」という 4 節の構造が再現されます。1 クラスが最頻である限り、argmax がそのクラスに張り付くのはモデルの欠陥ではなく多クラス分類の性質です。最後の行は、CSV のクラス名を 1 つ書き換えたファイルを `load` に渡して、整合チェックが例外を投げることを確かめたものです。

### 7.5 校正モニタリング

校正が良いことは設計時の test で確認しましたが、運用中も崩れていないかを見る必要があります。`build_kimarite_calibration.py` が月次で `data/estimate/kimarite/**` の `状態=realtime` 行と `results/realtime` の実績を突き合わせ、予測帯ごとに「予測した荒れ度」「実際に荒れた率(1 コース以外が 1 着)」「差 pt」「32 クラスの log-loss」を `calibration.csv` に書きます。KPI は「各予測帯で実測との差が ±5pt 以内」です。朝の暫定値(`daily` 行)は混ぜません。stdlib のみで書かれているのは、monthly-weights の実行環境に依存を増やさないためです。

### 7.6 fun-site での表示

fun-site 側は、バッチが `data/estimate/kimarite/YYYY/MM/DD.csv` を `KimariteRow` に読み(`kimarite-schemas.ts`)、`RacePrediction.upsetMeter` に daily / realtime の荒れ度だけを載せます。予想者に紐づかないので `RacePrediction` の直下に置き、予想者カードの外に 1 回だけ描画します。

```ts:packages/shared/src/types/prediction.ts(抜粋)
/**
 * 荒れ度メーター(レース単位)。予想者に紐づかないので `RacePrediction` 直下に持つ。
 * `1 − P(逃げ)` で、校正が取れている唯一の値。決まり手の argmax は出さない。
 */
export type UpsetMeter = {
  /** 朝バッチ時点の荒れ度 (0〜1)。 */
  readonly daily?: number;
  /** 直前情報反映後の荒れ度 (0〜1)。 */
  readonly realtime?: number;
};
```

`UpsetMeter.astro` は realtime があればそれを、なければ daily の値に「(朝時点)」を添えて出します。帯のしきい値は全体平均(約 46%)を中心に置いた目安です。

```ts:packages/web/src/components/UpsetMeter.astro(抜粋)
const value = meter?.realtime ?? meter?.daily;
const isRealtime = meter?.realtime !== undefined;

/** 表示用の帯。しきい値は全体平均 (約 46%) を中心に置いた目安。 */
const band = (v: number): { label: string; cls: string } => {
  if (v < 0.35) return { label: "堅め", cls: "bg-sky-100 text-sky-800 border-sky-300" };
  if (v < 0.55) return { label: "標準", cls: "bg-gray-100 text-gray-700 border-gray-300" };
  if (v < 0.7) return { label: "やや荒れ", cls: "bg-amber-100 text-amber-800 border-amber-300" };
  return { label: "荒れ", cls: "bg-rose-100 text-rose-800 border-rose-300" };
};
```

パーサ側で 1 つ注意点があります。`荒れ度` の空欄を `Number("")` に通すと 0(= 絶対に荒れない)になってしまうので、空欄は先に弾いて行ごと捨てます。表示の下には「1 コースが逃げない確率。過去実績から推定した値で、決まり手そのものは予測していません」という注記を固定で出しています。5 節の「出せる形と出せない形」をユーザーにもそのまま伝えるためです。

この荒れ度メーターは 2026-08-12 に投入され、翌 08-13 には同じ Stage1 を土台にした穴予想 `v10_kimarite` が買い目を出し始めました。セル確率から 3 連単 120 通りを合成し、強さポイントの Plackett-Luce とブレンドし、log-loss で A/B 判定する部分は第 21 章で扱います。

## 元資料

- [docs/design/ana_prediction.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/ana_prediction.md) — §1〜§6(穴の構造、モデル設計、検証、出力の見せ方)、§8(Phase 1 荒れ度メーター)、§10〜§12(レビュー指摘と解決)、§14(決まり手の表示方式)
- [scripts/boatrace/kimarite.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/kimarite.py) — `CELLS`、`cell_of`、`feature_names`、`build_features`
- [scripts/build_kimarite.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite.py) — 学習と係数 CSV の書き出し
- [scripts/build_kimarite_probs.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite_probs.py) — 係数 CSV からの推論と日次 CSV の upsert
- [scripts/build_kimarite_calibration.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite_calibration.py) — 校正モニタリング
- [docs/data/estimate.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) — 荒れ度メーター(決まり手セルモデル)のファイル構成とホールドアウト実測
- [docs/operations.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/operations.md) — 荒れ度メーターの運用
- [fun-site packages/web/src/components/UpsetMeter.astro](https://github.com/BoatraceCSV/fun-site/blob/main/packages/web/src/components/UpsetMeter.astro) — 表示コンポーネント
- [fun-site packages/shared/src/types/kimarite.ts](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/types/kimarite.ts)、[packages/batch/src/fetcher/kimarite-schemas.ts](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/fetcher/kimarite-schemas.ts) — 型と CSV パーサ
- [fun-site docs/web.md](https://github.com/BoatraceCSV/fun-site/blob/main/docs/web.md) — 荒れ度メーターの節

## 演習

`results/realtime` の公開 CSV(`https://boatracecsv.github.io/data/results/realtime/YYYY/MM/DD.csv`)1 か月分から、決まり手 × 1 着コースの分布を集計し、「逃げ_1」がどれだけ支配的かを確かめてください。`決まり手` 列は「逃　げ」「差　し」「抜　き」のように全角スペースが入っているので、正規化してから集計します。1 着コースは `{c}コース_艇番` が `1着_艇番` と一致するコース(実進入)で求めます。モデルが使う展示進入とは定義が違うので、値は 3.2 節の集計と厳密には一致しません。

```python:exercise_cells.py
import csv, glob
from collections import Counter

KIMARITE_MAP = {"逃　げ": "逃げ", "差　し": "差し", "まくり": "まくり",
                "まくり差し": "まくり差し", "抜　き": "抜き", "恵まれ": "恵まれ"}
ORDER = ["逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ"]

cells, n = Counter(), 0
for path in sorted(glob.glob("realtime/2026/08/*.csv")):
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            kim = KIMARITE_MAP.get(row["決まり手"].strip())
            winner = row["1着_艇番"].strip()
            course = next((c for c in range(1, 7)
                           if row[f"{c}コース_艇番"].strip() == winner), None)
            if kim is None or course is None:
                continue
            cells[(kim, course)] += 1
            n += 1

print(f"n = {n}")
for kim in ORDER:
    vals = [cells[(kim, c)] for c in range(1, 7)]
    print(f"{kim:<6s}", " ".join(f"{v / n * 100:6.2f}%" for v in vals),
          f"| {sum(vals) / n * 100:6.2f}%")
print(f"逃げ_1 = {cells[('逃げ', 1)] / n * 100:.1f}%")
```

2026 年 8 月分(31 日、n=4,798 レース)で実行した結果です。

```text
n = 4798
逃げ      51.67%   0.00%   0.00%   0.00%   0.00%   0.00% |  51.67%
差し       0.00%   8.25%   1.58%   1.88%   0.40%   0.21% |  12.32%
まくり      0.00%   3.52%   5.56%   5.11%   0.96%   0.52% |  15.67%
まくり差し    0.00%   0.00%   5.02%   2.61%   4.25%   0.88% |  12.76%
抜き       2.48%   0.98%   1.40%   0.69%   0.77%   0.38% |   6.69%
恵まれ      0.13%   0.21%   0.15%   0.19%   0.15%   0.08% |   0.90%
逃げ_1 = 51.7%
```

列は 1〜6 コース、右端は決まり手ごとの合計です。逃げ_1 が 51.7%(荒れ度の実測平均は 100 − 51.7 = 48.3%)で、2 位の 差し_2(8.3%)の 6 倍あります。次いで まくり_3(5.6%)、まくり_4(5.1%)、まくり差し_3(5.0%)が並びます。「逃げは 1 コースだけ」「まくり差しは 2 コースからは出ない」という構造も、1 か月分でそのまま見えます。この分布で argmax を取ると、どのレースでも逃げ_1 が最有力になりやすいことを 4 節と合わせて考えてみてください。余裕があれば、月を変えて逃げ_1 の割合がどの程度動くかも見てください。
