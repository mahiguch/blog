---
title: "的中率・回収率・log-loss: 何で判断するか"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 本当に知りたい値(回収率)と、それを代理する指標(log-loss)の使い分け。分散が大きい指標でモデルを選ぶと何が起きるか。信頼区間の幅から必要サンプル数を逆算する検出力の計算。同一レースで突き合わせるペア比較、多重比較の Holm 補正、中間指標の改善が本番 KPI に乗らない例 |
| システム | 的中率・回収率の母数の定義(返還・中止・不成立の除外)。指標を「主判定」「ガードレール」「体験指標」の 3 役に分けて運用する設計。万舟を本数ではなく賭け金 1 万円あたりで比べる理由 |

この章は本書の中核です。第 10 章で説明する予想者の退役判定も、第 21 章の穴予想 A案 / B案 の
比較も、判定の根拠はすべてこの章の考え方に立っています。数値は特に断りがない限り
boatracecsv の設計書に記録された **2026 年 8 月時点**の実測値で、母数 n を添えます。

## 1. 3 つの指標

本書で予想者の良し悪しを測る指標は 3 つあります。それぞれ何を測っていて、何を測れないかを
先に整理します。

### 1.1 的中率

的中率は「買い目のどれかが 3 連単の結果と一致したレース数 ÷ 母数」です。直感的で
説明しやすい反面、**点数を増やせば上がります**。120 通り全部を買えば 100% です。
control(`v1_basic`)は 1 レースあたり 11.5 点で的中率 45.6%、穴予想 `v10_kimarite` は
5.0 点で 12.4% です(test 3,527 レース、同一レース)。この 2 つの的中率を並べても、
どちらの予想が良いかは何も言えません。

### 1.2 回収率

回収率は「払戻合計 ÷ 購入額合計」です。1 点 100 円で買ったとき、点数 × 100 円が購入額、
的中したレースの 3 連単払戻金が払戻です。これが本当に知りたい値です。
控除率は 25% なので(第 1 章)、何も知らずに買い続ければ長期的には 75% に収束し、
100% を超えていれば市場に勝っていることになります。

問題は**分散が極端に大きい**ことです。1 レースの収支は「購入額を全額失う」か
「数千円〜数万円が返ってくる」かのどちらかで、平均配当 3,427 円の穴予想なら、1 レースあたりの
回収率は 0% か 685%(3,427 ÷ 500)のような値を取ります。この平均を 3,500 レースで取っても、
95% 信頼区間(CI)は **±12〜13pt** の幅を持ちます(§3 で計算します)。

### 1.3 log-loss

log-loss は確率予測の質を測る指標です。予想者が 3 連単 120 通りに確率分布 $p$ を出しているとき、
実際の結果 $y$ に対して

$$
\text{log-loss} = -\log p(y)
$$

を各レースで計算し、平均します。当たった出目に高い確率を置いていれば小さく、
低い確率しか置いていなければ大きくなります。一様分布(すべて 1/120)なら
$\log 120 = 4.7875$ で、これが「何も知らない」基準です。

| 予測(test 3,527 レース、3 連単 120 通り) | log-loss |
| --- | ---: |
| 一様(1/120) | 4.7875 |
| Plackett-Luce(強さpt、β=1.4) | 4.0325 |
| 決まり手モデル単体 | 3.9522 |
| ブレンド(決まり手 0.8 + PL 0.2) | 3.9364 |
| (参考)市場 = 3 連単オッズの正規化逆数 ※別サンプル 3,352 レース | 3.7965 |

回収率と違って、log-loss は**毎レース連続値が出ます**。的中したかどうかの 0/1 ではなく
「どのくらい惜しかったか」が数値に乗るので、1 レースあたりの散らばりが小さく、
少ないレースで差が決着します。これが本章の主題である「主判定を log-loss に置く」理由です。

### 1.4 3 指標の性格

| 指標 | 測っているもの | 点数を増やすと | 1 レースあたりの散らばり | 本当に知りたい値との距離 |
| --- | --- | --- | --- | --- |
| 的中率 | 買い目が当たる頻度 | 単調に上がる | 0/1 | 遠い(配当を無視) |
| 回収率 | 賭けの期待値 | 変わらない(理論上) | 0 か数百〜数千 % | これ自体 |
| log-loss | 確率分布の質 | 関係ない(買い目に依存しない) | 小さい(連続値) | 近いが同じではない(§5) |

log-loss は買い目を作る前の確率分布に対する指標なので、「何点買うか」「1 コース頭を
除くか」といった買い目ルールの影響を受けません。逆に言えば、log-loss が良くても
買い目ルールが悪ければ回収率は出ません。この距離が §5 の主題です。

## 2. 「回収率で選ぶ」と何が起きるか

回収率が本当に知りたい値なら、回収率が最大になるようにハイパーパラメータを選べば
よさそうに思えます。実際にやってみた記録が `notebooks/ana_prediction/report.md` にあります。

### 2.1 学習窓を回収率で選ぶ

穴予想 A案(`v9_suji`、第 21 章)は「1 着コースを与えたときの 2-3 着コースの条件付き分布」
(スジ表)を過去データから数えるだけのモデルで、パラメータは**学習窓の長さ**です。
窓を 1 か月から全履歴まで振り、valid(2026-06-25〜07-17、3,696 レース)と
test(2026-07-18〜08-11、3,532 レース)で回収率を測ったのが次の表です。

| 学習窓 | valid 回収率 | test 回収率 |
| --- | ---: | ---: |
| 1 か月 | **77.9%**(最良) | 78.3%(最下位) |
| 2 か月 | 77.1% | 83.6% |
| 3 か月 | 71.7% | **84.1%** |
| 4 か月 | 73.2% | 80.0% |
| 6 か月 | 73.2% | 82.9% |
| 全履歴 | 71.3%(最下位) | 80.6% |

**valid で最良だった 1 か月窓が、test では最下位です**。valid で最下位だった全履歴は
test では中位です。各セルの 95%CI は ±12〜14pt あり、6 つの構成はすべて互いの CI に
収まります。つまりこの表の順位は**ノイズ**で、valid の順位で選ぶことは valid のノイズに
過学習することと同じです。

### 2.2 同じデータを条件付き log-loss で見る

同じ 6 構成を、真の 1 着コースを与えたときの $P(\text{2着}, \text{3着} \mid \text{1着})$ の
log-loss で比べると、景色が変わります。

| 学習窓 | valid | test |
| --- | ---: | ---: |
| 一様(20 通り) | 2.9957 | 2.9957 |
| 1 か月 | 2.8257 | 2.8386 |
| 2 か月 | 2.8204 | 2.8311 |
| 3 か月 | 2.8177 | 2.8287 |
| 4 か月 | 2.8146 | 2.8275 |
| 6 か月 | 2.8144 | 2.8275 |
| 全履歴 | 2.8144 | 2.8274 |

窓長に対して**単調に改善して 4 か月で飽和し、valid と test で順序が完全に一致**します。
回収率では見えなかった構造が log-loss でははっきり見えます。本番構成の「全履歴」は
この表で選ばれました。

### 2.3 点数すら決められない

同じことは「何点買うか」でも起きます。B案(`v10_kimarite`)で 1 コース頭を除いた
確率上位 k 点を買う戦略の回収率は、valid では top3 が 80.5%、top5 が 76.3% で、
test では順位が逆になります(どちらも CI は ±10pt 級)。設計書は top5 を採用していますが、
それは「valid の最良」ではなく、**A案と同じ 5 点・同じ 500 円でペア比較できる**ことを理由に
事前に決めたルールです。回収率で選べないなら、比較可能性という別の基準で固定するしかありません。

### 2.4 モデルを替えると消える数字

回収率の分散は、サブグループに絞り込むとさらに広がります。設計書 §5.3 は、決まり手モデルの
Stage1 を GBM に替えた版とロジスティック回帰版で同じ戦略を評価しています。

| 戦略 | GBM 版 | ロジスティック版 | 判定 |
| --- | ---: | ---: | --- |
| 1 着≠1 の top5 | 85.2% | 84.9% | 安定 |
| 1 着≠1 の top12 | 83.0% | 81.6% | 安定 |
| 逃げ確率 下位 35% × top8 | 98.4% | 93.4% | 方向は同じだが振れる |
| 逃げ確率 下位 20% × top8 | 107.9% | 92.1% | 振れる。信用しない |
| 最有力セルが逃げでないレース(5.5%)× top3 | 122.4% | 78.8% | ノイズ。n≈200 |

100% を超えて見えたセルは、いずれもサンプルが小さく、モデルを替えると消えました。
「回収率 122%」のような数字を見たときは、まず n を見て、次にモデルを替えて再現するかを
確かめる、という手順を習慣にしてください。

:::message
バックテストで「回収率 100% 超え」が出たときに疑うべき順番は、(1) n が小さくないか、
(2) test を見てルールを選んでいないか(設計書の B3 指摘)、(3) モデルや乱数シードを
替えても残るか、です。設計書 §5.3 の 122.4% は (1) と (3) の両方で消えています。
:::

## 3. 検出力を逆算する

「回収率では決着しない」を感覚ではなく数で示します。設計書 §13.3 の
「差 +4.2pt を有意にするには約 34,700 レース、8.2 か月」という数字を、式から再現します。

### 3.1 CI の半幅と 1 レースあたりの標準偏差

n レースの平均から作った 95%CI の半幅 $h$ は、1 レースあたりの値の標準偏差を $\sigma$ として

$$
h = 1.96 \cdot \frac{\sigma}{\sqrt{n}}
$$

です。逆に、観測された半幅と n から $\sigma$ が求まります。

$$
\sigma = \frac{h \sqrt{n}}{1.96}
$$

A案 vs B案 の回収率差(B − A)は test 3,527 レースで +4.2pt、95%CI [−9.4, +17.2] でした
(ペア bootstrap、同一レース)。半幅は 13.3pt です。ここから

$$
\sigma_{\text{回収率差}} = \frac{13.3 \times \sqrt{3527}}{1.96} \approx 403 \text{ pt}
$$

つまり **1 レースあたりの回収率差の標準偏差は約 400pt** です。500 円買って 0 円か
数千円かが返ってくる分布どうしの差なので、この大きさは自然です。

同じ 3,527 レースで、3 連単 log-loss の改善(PL 単体 → ブレンド)は +0.0961 nat、
95%CI [+0.0795, +0.1126] で半幅 0.0166 nat です。

$$
\sigma_{\text{log-loss差}} = \frac{0.0166 \times \sqrt{3527}}{1.96} \approx 0.50 \text{ nat}
$$

:::message
設計書には $\sigma$ の値そのものは載っていません。上の 403pt と 0.50 nat は、
設計書の CI と n から本書が逆算した値です。
:::

### 3.2 効果量から必要サンプル数を出す

観測された差(効果量)を $\delta$ とします。CI が 0 をちょうど含まなくなるのは半幅が $\delta$ に
等しくなるときなので、必要な n は

$$
n' = \left( \frac{1.96\,\sigma}{\delta} \right)^2 = n \left( \frac{h}{\delta} \right)^2
$$

です。右の形は「いま n レースで半幅 $h$ なら、半幅を $\delta$ まで縮めるには n を
$(h/\delta)^2$ 倍にする」と読めます。半幅は $\sqrt{n}$ に反比例するので、
**幅を半分にするには 4 倍のレースが要ります**。

回収率差に当てはめます。

$$
n' = 3527 \times \left( \frac{13.3}{4.2} \right)^2 \approx 35{,}000
$$

設計書の 34,700 は、差を丸める前の値(84.87% − 80.63% ≒ 4.24pt)で計算すると
$3527 \times (13.3/4.24)^2 = 34{,}704$ となり、一致します。test 期間は 25 日で 3,527 レース、
1 日あたり 141 レースなので、34,700 レースは 246 日、**約 8.2 か月**です。
差が 2pt なら $3527 \times (13.3/2.0)^2 \approx 156{,}000$ レースで、設計書の 153,000
(丸め方の差)と同じく **約 36 か月**になります。

log-loss に同じ式を当てはめると

$$
n' = 3527 \times \left( \frac{0.0166}{0.0961} \right)^2 \approx 105
$$

で、**100 レース強、1 日分にも満たない量で決着**します。設計書の表にある 418 レースは、
半幅ではなく CI の全幅(0.0332 nat)を効果量に当てた、より保守的な数え方に対応します
($3527 \times (0.0332/0.0961)^2 = 421$)。どちらで数えても「0.1 か月」であることに
変わりはなく、設計書が「n = 3,527 で既に効果の 5.8 倍の精度がある」
(0.0961 ÷ 0.0166 = 5.8)と書いているのはこの意味です。

| 判定指標 | 半幅(n=3,527) | 観測された効果 | 必要レース数 | 所要期間(141 レース/日) |
| --- | ---: | ---: | ---: | ---: |
| 回収率差 | ±13.3pt | +4.2pt | 約 34,700 | 約 8.2 か月 |
| 回収率差(2pt を検出) | ±13.3pt | 2.0pt | 約 153,000 | 約 36 か月 |
| 3 連単 log-loss 差 | ±0.0166 nat | +0.0961 nat | 約 418(半幅基準なら約 105) | 約 0.1 か月 |

![CI 半幅と n の関係。回収率差と log-loss 差で、観測された効果量と交わる n が 2 桁以上違う](/images/boatrace-ml-system/09-ci-halfwidth-vs-n.png)
<!-- 図: 横軸 n(対数、10^2〜10^6)、縦軸を 2 段にする。上段: 回収率差の 95%CI 半幅 = 1.96×403/√n の曲線と、水平線 4.2pt・2.0pt。交点に 34,700 と 153,000 の目盛りを打ち、横軸の上に「1 日 = 141 レース」「8.2 か月」「36 か月」を添える。下段: log-loss 差の半幅 = 1.96×0.503/√n の曲線と水平線 0.0961 nat。交点 105(半幅基準)と 418(全幅基準)を打つ。3,527 の位置に縦の点線を入れて「test 期間」と書く -->

:::message
ここでの「必要 n」は「CI がちょうど 0 を含まなくなる n」で、統計的検出力で言えば
約 50% に相当します。慣例的な検出力 80% を要求するなら、係数が
$(1.96 + 0.84)^2 / 1.96^2 \approx 2.04$ 倍になり、回収率差 4.2pt には約 71,000 レース
(17 か月)が要ります。設計書の 34,700 / 8.2 か月は緩い側の見積もりで、
それでも実用にならないことが結論の要点です。
:::

### 3.3 結論: 指標に役割を与える

回収率で A案と B案を比べると 8 か月、慎重に見れば 1 年半かかります。その間に
番組の傾向もモデルも変わるので、実質「決着しない」と同じです。そこで設計書 §13.3 は
指標に役割を分けました。

| 指標 | 役割 | 判定 |
| --- | --- | --- |
| **3 連単 log-loss** | **主判定**。確率の質を上げているか | 数週間で決着。B案が有意に上回らなくなれば B案を退役 |
| 回収率 | **ガードレール**。破滅的な劣化の検知だけ | control(`v1_basic`)比で **−7pt 級**の劣化が出たら退役。A案 vs B案 の微差は判定に使わない |
| 万舟/1 万円・平均配当 | **体験指標**。穴予想として成立しているか | 目標値を置くが有意差判定はしない(検出力が足りない) |
| P(逃げ) の校正誤差 | B案のみ。荒れ度メーターの品質 | 各予測帯で ±5pt 以内 |

「−7pt 級」という閾値は、§4 で見る v6 / v7 / v8 の退役が −6.9〜−10.6pt で、
**13〜20 日で検出できた**という実績から来ています。大きな劣化は回収率でも
すぐ見えるので、回収率をガードレールに使うのは合理的です。一方、+4.2pt 程度の
改善は回収率では見えないので、主判定を別の指標に委ねます。

![指標の 3 役。主判定 = log-loss、ガードレール = 回収率、体験指標 = 万舟/1 万円と平均配当](/images/boatrace-ml-system/09-metric-roles.png)
<!-- 図: 3 つの箱を横に並べる。左「主判定: 3 連単 log-loss」(数週間で決着、logloss.csv の CI 下限 < 0 で退役)、中央「ガードレール: 回収率」(control 比 −7pt 級で退役、微差は見ない)、右「体験指標: 万舟/1 万円・平均配当・点数」(目標値のみ、検定しない)。下に共通の帯で「母数 = 直前買い目が組めた確定レース(§6)」 -->

## 4. ペア比較と多重比較

主判定でもガードレールでも、「差」の CI と p 値の計算方法が問題になります。
boatracecsv の退役判定は次の手順で統一されています(registry.py 冒頭コメント、estimate.md)。

### 4.1 なぜ同一レースで突き合わせるか

予想者 A と B を別々の期間で測って回収率を並べても、期間の違い(荒れた節が
入っていたか)が差に混ざります。設計書 §5.2 は当初、穴予想の 84.9%(95%CI [74, 97])を
別期間の control ≒ 86% と並べていましたが、この CI は control の値を含んでいて
「差がないことすら示せない」状態でした。そこで §11.2 では fun-site の買い目生成を Python で
再実装し、**同じ test 3,527 レース**で control を再現してから比べています。

同一レースで比べると、両者が同じレースの荒れ・堅さを共有するぶん、差の分散が小さく
なります。bootstrap でも並べ替え検定でも、**レース単位の対応を壊さない**ことが要点です。

### 4.2 手順

1. **母数**: 直前(realtime)買い目が組めた確定レースのみ。各予想者の `started_at` 以降で
   control と同一レースを突き合わせる(§6)
2. **ペア bootstrap(20,000 反復)**: レースを復元抽出し、**同じ抽出**で A と B の回収率を
   計算して差を取る。2.5 / 97.5 パーセンタイルが 95%CI
3. **ペア並べ替え検定**: 1 レースあたりの収支差 $d_i = (\text{払戻}_B - \text{購入}_B) - (\text{払戻}_A - \text{購入}_A)$ の
   符号を無作為に反転し、観測された平均より極端になる割合を p 値とする
4. **頑健性**: 差分の大きい上位 20 レースを除外しても差が変わらないか(外れ値依存の確認)。
   日次で control を下回った日数の**符号検定**。買い目点数の分布を control に揃えて
   **標準化**した回収率
5. **多重比較**: 複数の予想者を同時に判定するときは **Holm 補正**

2026-08-09 の判定結果(estimate.md、registry.py)を示します。

| 予想者 | n | 回収率 | control | 差 | 95%CI | p(並べ替え) | Holm 補正 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `v6_course` | 3,002 | 79.06% | 85.97% | **−6.91pt** | [−13.1, −0.5] | 0.0047 | 0.016 |
| `v7_aggregate` | 2,717 | 78.10% | 85.86% | **−7.76pt** | [−13.9, −1.7] | 0.0040 | 0.016 |
| `v8_aionly` | 1,892 | 77.30% | 87.92% | **−10.62pt** | [−18.5, −2.9] | 0.0001 | 0.0005 |
| (参考)`v4_motor` | 3,035 | 85.97% | 85.66% | +0.30pt | [−2.4, +3.6] | 0.884 | 0.884 |
| (参考)`v5_slit` | 3,035 | 82.95% | 85.66% | −2.72pt | [−7.0, +1.2] | 0.377 | 0.755 |

頑健性の確認では、日次で control を下回った日が `v6_course` 17/20 日(符号検定 p=0.0026)、
`v8_aionly` 13/13 日(p=0.0002)でした。3 者とも control より買い目点数が多い
(`v8_aionly` は 14.7 点 vs 11.7 点)のですが、点数分布を control に揃えて標準化しても
回収率は 76〜78% にとどまり、「点数ではなく選定そのものの問題」と判断されています。

`v4_motor` と `v5_slit` の CI が ±3〜4pt と狭いことにも注目してください。
両者は control と成分がほぼ同じで買い目も大きく重なるため、レース単位の差 $d_i$ が
小さく、ペア比較の恩恵が最大限に出ています。逆に A案 vs B案 は買い目 5 点のうち平均
2.62 点しか重ならず、差の分散が大きいまま(±13pt)です。**ペア比較の効き方は、2 つの
予想者がどれだけ同じ賭けをしているかで決まります**。

### 4.3 Holm 補正

5 つの予想者を同時に p < 0.05 で判定すると、どれも本当は差がなくても 1 つ以上が
「有意」になる確率が 1 − 0.95⁵ ≈ 23% あります。Holm 補正は、p 値を小さい順に並べ、
i 番目の p を (m − i + 1) 倍して(m は検定数)、単調性を保つ補正です。上の表では
`v8_aionly` の 0.0001 × 5 = 0.0005、次の `v7_aggregate` の 0.0040 × 4 = 0.016、
`v6_course` の 0.0047 × 3 = 0.014 → 前の値を下回らないよう 0.016、という計算になっています。

ただし設計書自身が注意しているとおり、v6 / v7 / v8 は `course` 成分を共有しているので
独立な 3 検定ではなく、実質「`course` 仮説を 1 回否定した」重みで読むべきです。
補正は数を数えれば機械的にできますが、**何が独立な仮説なのか**は人が決めるしかありません。

### 4.4 簡略版コード: ペア bootstrap とペア並べ替え検定

退役判定のコードは検討時の scratchpad にあり、リポジトリには残っていません。
`notebooks/ana_prediction/suji_backtest.py` の `summarize()`(1 予想者の bootstrap CI)と
`kimarite_backtest.py` の paired bootstrap を組み合わせて、本質だけを書き直します。

```python:paired_test.py
import numpy as np

RNG = np.random.default_rng(20260809)


def paired_bootstrap_ci(cost_a, ret_a, cost_b, ret_b, n_boot=20_000):
    """同一レースで突き合わせた回収率差 (B − A, pt) の 95%CI。"""
    n = len(cost_a)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = RNG.integers(0, n, n)              # レース単位で復元抽出
        roi_a = ret_a[idx].sum() / cost_a[idx].sum() * 100
        roi_b = ret_b[idx].sum() / cost_b[idx].sum() * 100
        boots[i] = roi_b - roi_a                 # 同じ idx を両者に使うのがペアの要点
    diff = ret_b.sum() / cost_b.sum() * 100 - ret_a.sum() / cost_a.sum() * 100
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return diff, lo, hi


def paired_permutation_p(profit_a, profit_b, n_perm=20_000):
    """1 レースあたり収支差 d = B − A の符号を無作為に反転する並べ替え検定(両側)。"""
    d = profit_b - profit_a
    observed = abs(d.mean())
    signs = RNG.choice([-1.0, 1.0], size=(n_perm, len(d)))
    null = np.abs((signs * d).mean(axis=1))
    return float((null >= observed).mean())


def sign_test_p(daily_a, daily_b):
    """日次回収率で B が A を下回った日数の両側符号検定。"""
    from math import comb
    worse = int((daily_b < daily_a).sum())
    n = len(daily_a)
    tail = sum(comb(n, k) for k in range(0, min(worse, n - worse) + 1)) / 2 ** n
    return worse, n, min(1.0, 2 * tail)


def holm(pvalues):
    """Holm 補正。小さい p から順に (m − 順位) 倍し、単調性を保つ。"""
    m = len(pvalues)
    order = np.argsort(pvalues)
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, pvalues[i] * (m - rank))
        adjusted[i] = min(1.0, running)
    return adjusted
```

`paired_bootstrap_ci` の要点は 1 行です。`idx` を 1 回引いて、A と B の両方に同じ `idx` を
使う。これを別々に引くと非ペアの bootstrap になり、レース間の相関が捨てられます。

合成データで動かした結果です。5 点・的中率 12%・平均配当 3,400 円の穴予想 A と、
半分のレースで A と同じ結果になる B を 3,527 レース分作りました。

```
A 回収率 70.3%  B 回収率 77.5%
ペア bootstrap: 差 +7.2pt  95%CI [-7.9, +22.1]  半幅 15.0pt
ペア並べ替え検定 p = 0.348
Holm: [0.016 0.016 0.0005 0.884 0.754]
```

半幅が 15pt と、設計書の ±13.3pt と同じ桁になります。7pt の差があっても
p = 0.35 で有意になりません。`holm()` に上の表の 5 つの p 値を渡すと、
estimate.md の Holm 補正列(0.016 / 0.016 / 0.0005 / 0.884 / 0.755)が再現できます
(0.754 と 0.755 の違いは、表の p 値が丸められているためです)。

### 4.5 簡略版コード: log-loss の主判定

主判定の log-loss は `scripts/build_kimarite_logloss.py` が月次で集計し、
`data/estimate/kimarite/tables/logloss.csv` に書き出します。CI は bootstrap ではなく
**レース単位の差の標準誤差による正規近似**です。差 $d_i$ はレース間で独立なので、
この n では bootstrap と実質同じ結果になり、stdlib だけで済みます。

```python:build_kimarite_logloss.py(抜粋)
import math


def race_logloss(probs: dict[tuple[int, int, int], float], truth: tuple[int, int, int]) -> float:
    """1 レース分。120 通りの分布から真の出目の確率を引き、−log を取る。"""
    return -math.log(max(probs.get(truth, 0.0), 1e-12))


def summarize(label: str, pairs: list[tuple[float, float]]) -> list:
    """(対照の log-loss, 実験の log-loss) の列 → 平均と改善 nat の 95%CI(正規近似)。"""
    n = len(pairs)
    pl = sum(a for a, _ in pairs) / n
    mixed = sum(b for _, b in pairs) / n
    diffs = [a - b for a, b in pairs]          # 正なら実験側の勝ち
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    half = 1.96 * math.sqrt(var / n)           # d_i が独立なので SE = SD/√n
    return [label, n, f"{pl:.4f}", f"{mixed:.4f}",
            f"{mean:+.4f}", f"{mean - half:+.4f}", f"{mean + half:+.4f}"]
```

`max(..., 1e-12)` は、真の出目に確率 0 を置いたときに log が発散するのを防ぐ
クリッピングです。実装では対照が `plackett_luce(z, PL_BASELINE_BETA)`(強さpt だけで作った
分布、β=1.4)、実験が `blend(p1, tab, z)`(第 21 章のブレンド)で、両方を同じレースで評価して
`pairs` に積みます。

出力の 1 行は `集計月 / n / PL_logloss / ブレンド_logloss / 改善nat / 95%CI下限 / 95%CI上限` です。
ホールドアウトでは改善 **+0.1186 nat [+0.1003, +0.1376]**(n=3,614)でした。
本番投入後の 2026-08 分(realtime 確定レース n=2,639)は `logloss.csv` に
**+0.1311 nat [+0.1091, +0.1530]** と記録されており、ホールドアウトの水準を保っています。
退役ルールは「`95%CI下限` が 0 を下回ったら」で、これは第 21 章で扱います。

## 5. 中間指標の改善が本番 KPI に乗らない

log-loss を主判定にするなら、「log-loss が良ければ回収率も良い」と言いたくなります。
そうならなかった例が `v6_course` です。この失敗が、log-loss を主判定にできる条件を教えてくれます。

### 5.1 テーブル単体では改善していた

`v6_course` は control の枠番pt(場 × 季節 × コースの 1 着率)を、場 × レース番号 × コースの
1 着率テーブルに差し替えた予想者です(第 10 章)。テーブルの収縮パラメータ k は、
勝ちコースの 6 値確率予測を Brier と log-loss で評価して選ばれています
(train 36,105 レース / test 3,074 レース)。

| 構成 | Brier | log-loss |
| --- | ---: | ---: |
| k=0(生セル率) | 0.6359 | 1.3654 |
| k=20 | 0.6350 | 1.3357 |
| **k=50(採用)** | **0.6349** | **1.3316** |
| k=100 | 0.6359 | 1.3305 |
| 場のみ(レース番号無視) | 0.6473 | 1.3468 |

レース番号次元を足すと、場のみに比べて Brier も log-loss も一貫して改善しています。
中間指標としては正しい改善です。

### 5.2 本番では回収率が下がった

ところがエンドツーエンド(強さpt 1 位 = 勝者の的中率、2026-07-01〜19 の 2,953 レース)では
`v1_basic` 55.98% に対して `v6_course` 55.71% と有意差がなく、本番投入後のペア比較
(2026-07-21〜08-09、n=3,002)では **79.06% vs 85.97%、−6.91pt、95%CI [−13.1, −0.5]、
p=0.0047(Holm 補正後 0.016)** で退役しました。

| | `v6_course` | control `v1_basic` |
| --- | ---: | ---: |
| 回収率 | 79.06% | 85.97% |
| 買い目の的中率 | **46.8%** | 46.1% |
| 点数 / レース | 13.0 | 11.6 |
| 点数分布を control に揃えた回収率 | 77.5% | — |

**的中率は v6 のほうが高い**のに、回収率は低い。これは「堅い決着は当てるが、安いオッズを
厚く買って期待値を落とす負け方」に見える、と設計書は書いています。レース番号ごとの
イン強度をテーブルで学んだ結果、インが強いレースでインを厚く買うようになり、
それは市場も知っているので配当が安い、という構図と考えられます。

### 5.3 何を測っていたか

ここで測っていた log-loss は「**勝ちコースの 6 値分布**」のものです。買い目は 6 値分布から
直接作られるのではなく、偏差値化 → 場別重みで線形結合 → 1 マーク走行距離 → ±0.10 窓の
フォーメーション、というパイプラインを通ります(第 7 章、第 8 章)。テーブル単体の較正が
改善しても、この線形結合パイプラインの着順精度にそのまま乗らない、というのが設計書の観測です。

一方、§3 で主判定にした log-loss は「**3 連単 120 通りの分布**」のもので、
`v10_kimarite` の買い目はその分布の上位 5 点をそのまま取ります。測っている分布と
買い目を作る分布が同じです。log-loss を主判定に置けるのは、この条件が
満たされているときだと考えられます。それでも買い目ルール(1 コース頭を除く、5 点に固定)は
log-loss の外にあるので、回収率のガードレールは外せません。

:::message alert
中間指標が改善したことを「本番も良くなるはず」の根拠にしないでください。
v6 の教訓は、(1) 中間指標は採否の根拠にならず、採否は本番 KPI のペア比較で決めること、
(2) 主判定に使う指標は、買い目を作る対象そのものを測っていること、の 2 点です。
:::

## 6. 母数を定義する

ここまでの指標はすべて「母数」の定義に依存します。母数を曖昧にすると、
的中率も回収率もサイトの表示と検定で食い違います。fun-site と boatracecsv は次の規約で揃えています。

### 6.1 数えるレース、数えないレース

fun-site `docs/domain.md` の定義です。

- **的中率 = 的中レース数 ÷ 母数、回収率 = 払戻合計 ÷ 購入額合計**
- 母数は**結果が確定したレース(1〜3 着が揃う。`isSettledResult`)かつ買い目が組めたレース**のみ
- 結果未着(当日進行中)・中止・不成立・返還のレースは、分子(的中数・払戻)と分母
  (母数・購入額)の**両方**から除外する

返還レースを「回収率 100% のレース」として計上する流儀もありますが、ここでは丸ごと除外します。
着順が出ず予想の当否を判定できないレースを母数に入れない、という方針で、購入額を
計上しない扱いは全額返還の会計上も整合します。

`isSettledResult` は 1〜3 着の艇番が揃っていて互いに異なることを確認するだけの関数です。

```ts:packages/shared/src/utils/race-result.ts
export const isSettledResult = (result: RaceResultRow | undefined): boolean => {
  if (!result) return false;
  const top = extractTopThree(result);
  if (!top) return false;
  const [a, b, c] = top;
  return a !== b && b !== c && a !== c;
};
```

集計側(`packages/batch/src/aggregator/predictor-stats.ts`)は、さらに
**直前(realtime)買い目のみ**を対象にします。当日(daily)の買い目は進入コースも強さpt も
暫定値だからで、当日の的中数は `dailyHitCount` に参考値として残すだけです。
「直前買い目が組めた」の判定は `betCostYen > 0` です。

boatracecsv 側の主判定(`build_kimarite_logloss.py`)も、**状態=realtime かつ確定したレース**
だけを対象にしており、回収率の母数と同じ規約です。2 つのリポジトリで母数の定義が
ずれると「log-loss は良いのに回収率が悪い」が母数の違いで起きうるので、揃えておく必要があります。

### 6.2 万舟は本数で比べない

穴予想の価値は回収率だけでは測れません。「当たらないが当たれば大きい」ことを見るために、
fun-site は次の体験指標を集計しています(`docs/batch.md`)。

| フィールド | 内容 |
| --- | --- |
| `hitPayoutYen` / `averagePayoutYen` | 的中レースの払戻総額と平均配当。分母は**的中数**(レース数ではない) |
| `averageBetCount` | レースあたりの購入点数 |
| `bigHitCount` | 万舟(3 連単 1 万円以上)の的中数 |
| `bigHitPer10kYen` | **賭け金 1 万円あたり**の万舟的中数 |

万舟を素の本数で比べると、点数を多く買う予想者ほど有利です。test 3,527 レースの
同一レース比較では、穴予想(5.0 点)が 21 本、control(11.5 点)が 40 本で、本数では
穴予想が負けています。しかし control は 2.3 倍の金額を賭けているので、賭け金 1 万円あたりに
直すと **0.12 vs 0.10** で逆転します。この指標は点数を増やすほど伸び(穴 top5 0.12 /
top8 0.14 / top12 0.18)、回収率は k に対してほぼ横ばいなので、設計書は
「k は回収率ではなく体験の KPI で決めるべき」としています。

```ts:packages/batch/src/aggregator/predictor-stats.ts(抜粋)
/** 万舟 (高配当) の下限 (円)。3連単の配当分布の上位 16% がここ。 */
export const BIG_PAYOUT_THRESHOLD_YEN = 10_000;

const accumulate = (
  acc: PredictorMonthlyStats,
  betCostYen: number,
  payoutYen: number,
  realtimeHit: boolean,
  betCount: number,
): PredictorMonthlyStats => {
  const raceCount = acc.raceCount + 1;
  const hitCount = acc.hitCount + (realtimeHit ? 1 : 0);
  const totalCost = acc.betCostYen + betCostYen;
  const totalPayout = acc.payoutYen + payoutYen;
  const hitPayoutYen = acc.hitPayoutYen + (realtimeHit ? payoutYen : 0);
  const bigHitCount =
    acc.bigHitCount + (realtimeHit && payoutYen >= BIG_PAYOUT_THRESHOLD_YEN ? 1 : 0);
  const totalBetCount = (acc.averageBetCount ?? 0) * acc.raceCount + betCount;
  return {
    ...acc,
    raceCount,
    hitCount,
    betCostYen: totalCost,
    payoutYen: totalPayout,
    recoveryRate: totalCost > 0 ? totalPayout / totalCost : null,
    hitPayoutYen,
    averagePayoutYen: hitCount > 0 ? hitPayoutYen / hitCount : null,
    averageBetCount: raceCount > 0 ? totalBetCount / raceCount : null,
    bigHitCount,
    bigHitPer10kYen: totalCost > 0 ? bigHitCount / (totalCost / 10_000) : null,
  };
};
```

分母が 0 のときは `null` を返し、0 で割った `NaN` や `Infinity` を JSON に載せない
ようにしています。`averagePayoutYen` の分母が `hitCount` である点も、
表示と集計を食い違わせないための明示です。

体験指標は §3.3 の役割分担どおり、**目標値は置くが有意差判定はしません**。
万舟/1 万円の A案 − B案 の差は −0.045、95%CI [−0.108, +0.017] で、回収率と同じく
検出力が足りないからです。実際、`v9_suji` の退役判断(2026-08-22、本番 1,511 レース)では
体験指標は A案が上(平均配当 3,949 円 vs 3,035 円、万舟/1 万円 0.133 vs 0.066)でしたが、
確率モデルを持ち主判定に載る B案が残されました。「穴らしさ」を優先すれば判断が逆になりうる、
という記録が残されているのは、指標の役割分担を先に決めていたからです(第 10 章)。

### 6.3 この章のまとめ

- 的中率は点数で操作できる。回収率は本当に知りたい値だが 1 レースあたりの標準偏差が
  約 400pt あり、+4pt の差を見るには 8 か月以上かかる
- log-loss は 1 レースあたりの標準偏差が約 0.5 nat で、同じ効果を 1 日分で検出できる。
  ただし主判定に使えるのは、買い目を作る分布そのものを測っているとき
- 差は必ず同一レースで突き合わせ、ペア bootstrap とペア並べ替え検定で CI と p を出す。
  複数を同時に判定するときは Holm 補正。ただし何が独立な仮説かは人が決める
- 母数は「直前買い目が組めた確定レース」に統一し、返還・中止・不成立は分子分母から除く
- 万舟は `bigHitPer10kYen` で比べる

## 元資料

- [docs/design/ana_prediction.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/ana_prediction.md) §5.1〜5.4(log-loss と回収率の実測、モデル差による振れ)、§7(KPI)、§11.2(ペア比較の理由)、§13.2〜13.3(検出力の逆算、主判定と役割分担)
- [notebooks/ana_prediction/report.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/notebooks/ana_prediction/report.md)(なぜ回収率で選ばないか、条件付き log-loss、点数すら決められない)
- [scripts/boatrace/predictors/registry.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py) 冒頭コメント(退役判定の検定結果)
- [docs/data/estimate.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md)(退役ノートの比較表、`logloss.csv` のスキーマと退役ルール)
- [docs/design/course_strength_v6.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/course_strength_v6.md) §2(Brier / log-loss での k 選定)と末尾(退役の記録)
- [scripts/build_kimarite_logloss.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite_logloss.py)(log-loss の 95%CI の計算)
- [notebooks/ana_prediction/suji_backtest.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/notebooks/ana_prediction/suji_backtest.py) の `summarize()`、[kimarite_backtest.py](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/notebooks/ana_prediction/kimarite_backtest.py)(bootstrap CI)
- fun-site [docs/domain.md](https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md)(的中率・回収率の母数)、[docs/batch.md](https://github.com/BoatraceCSV/fun-site/blob/main/docs/batch.md)(予想者統計の体験指標)
- fun-site [packages/batch/src/aggregator/predictor-stats.ts](https://github.com/BoatraceCSV/fun-site/blob/main/packages/batch/src/aggregator/predictor-stats.ts)、[packages/shared/src/utils/race-result.ts](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/race-result.ts)

## 演習

1. `v10_kimarite` の直前買い目(`https://boatracecsv.github.io/data/estimate/kimarite/picks/YYYY/MM/DD.csv`
   の `状態 == "realtime"` 行、`買い目1`〜`買い目5`、1 点 100 円)と 3 連単払戻
   (`https://boatracecsv.github.io/data/results/payouts/YYYY/MM/DD.csv` の `3連単_組番` / `3連単_払戻金`)
   を `レースコード` で JOIN し、2026-08-13〜08-31 の回収率と、その 95%CI を bootstrap(20,000 反復)で
   求めてください。母数は `3連単_組番` が入っているレースだけにします(§6.1)。
   半幅が本文で見た ±10〜13pt 級になることを確かめてください。次のコードを出発点にできます。

   ```python:exercise_roi_ci.py
   import numpy as np
   import pandas as pd

   BASE = "https://boatracecsv.github.io/data"
   days = pd.date_range("2026-08-13", "2026-08-31")
   picks = pd.concat(pd.read_csv(f"{BASE}/estimate/kimarite/picks/{d:%Y/%m/%d}.csv", dtype=str) for d in days)
   pay = pd.concat(pd.read_csv(f"{BASE}/results/payouts/{d:%Y/%m/%d}.csv", dtype=str) for d in days)

   rt = picks[picks["状態"] == "realtime"]
   df = rt.merge(pay[["レースコード", "3連単_組番", "3連単_払戻金"]], on="レースコード")
   df = df[df["3連単_組番"].notna() & (df["3連単_組番"] != "")]
   combos = df[[f"買い目{i}" for i in range(1, 6)]].to_numpy()
   cost = np.full(len(df), 5 * 100.0)
   hit = (combos == df["3連単_組番"].to_numpy()[:, None]).any(axis=1)
   ret = np.where(hit, df["3連単_払戻金"].astype(float), 0.0)

   rng = np.random.default_rng(0)
   n = len(df)
   boots = np.array([ret[idx].sum() / cost[idx].sum() * 100
                     for idx in (rng.integers(0, n, n) for _ in range(20_000))])
   lo, hi = np.percentile(boots, [2.5, 97.5])
   print(f"n={n} 回収率 {ret.sum()/cost.sum()*100:.1f}% 95%CI [{lo:.1f}, {hi:.1f}]")
   ```

2. 同じデータで、期間を 08-13〜08-19 の 1 週間に絞ったときの CI の半幅を求め、
   19 日分の半幅と比べてください。§3.2 の「幅を半分にするには 4 倍のレースが要る」が
   成り立っているか確認します。
3. 1 の `df` から、的中したレースの `3連単_払戻金` が 10,000 円以上の本数を数え、
   `bigHitPer10kYen`(本数 ÷ (購入額合計 ÷ 10,000))を計算してください。
   買い目を上位 3 点だけにしたときの値と比べ、点数で指標がどう動くかを見てください。
