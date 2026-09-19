---
title: "偏差値という共通言語: 枠番pt・選手pt・展示pt・気象pt"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 標準化(z スコア)と偏差値、「レース内」と「場別」の 2 段階標準化の使い分け、欠損補完値を平均以外にする判断、線形回帰係数を特徴量として使う |
| システム | 特徴量関数の粒度(1 艇 1 素点)、daily / realtime での成分の切り替え(中立値固定・引き継ぎ)、下流(fun-site)が小数第 2 位まで再現できる手順の明文化 |

第 2 章と第 3 章で集めた CSV から、いよいよ予想の材料を作ります。boatrace-fun.net の予想者 `v1_basic` は **枠番・選手・モーター・展示・気象** の 5 成分を「偏差値pt」に揃え、場別に学習した重みで足し合わせて「強さpt」を出します。この章では 5 成分のうち、モーター以外の 4 つの素点をどう作り、どう偏差値に直すかを扱います。モーターpt は履歴集計とベイズ収縮を伴うので第 5 章に譲り、重みの学習は第 7 章で扱います。

## 1. なぜ偏差値にするか

### 素点の単位はばらばら

4 成分の素点(標準化前の生の値)は、それぞれ別の単位と分布を持っています。2026 年 8 月の重みファイル `weights/v1_basic/2026-08.csv` から桐生の行を抜くと、素点の平均 μ と標準偏差 σ は次のようになっています(学習窓は 2026-02〜2026-07、n_samples = 6,479 行)。

| 成分 | 素点の意味 | μ(桐生) | σ(桐生) |
| --- | --- | --- | --- |
| 枠番 `waku` | 場 × 季節 × コース別の平均得点(1 着 10 点〜6 着 1 点) | 5.047 | 1.365 |
| 選手 `racer` | 近況 10 節の着順をグレード別に得点化した平均 | 53.79 | 4.958 |
| 展示 `exhibit` | 展示 4 系列のレース内偏差値の平均 | 50.00 | 6.344 |
| 気象 `weather` | 気象回帰係数 × 当日気象(コース別の有利pt変動) | −0.0001 | 0.1748 |

枠番の素点は 3〜8 の範囲、選手は 45〜100、展示は 50 前後、気象は ±0.3 程度です。このまま重み付き和を取ると、重みの値が「その成分をどれだけ信じるか」ではなく「単位の換算率」になってしまい、重みを読んでも何も分かりません。

そこで各成分を **平均 50・標準偏差 10** の偏差値に写します。

```
z   = (素点 − μ) / σ
pt  = 50 + 10 × z
寄与 = w × pt
強さpt = Σ 寄与
```

重み w を非負かつ Σw = 1 に制約して学習する(第 7 章)ので、強さpt も平均 50・標準偏差 10 前後のスケールに収まり、「寄与」の列がそのまま「この艇が強い理由の内訳」になります。

![素点から寄与までの流れ](/images/boatrace-ml-system/04-hensachi-pipeline.png)
<!-- 図: 4 成分(枠番・選手・展示・気象)を横に並べ、それぞれ「素点(単位が違う: 7.43 / 48 / 45.48 / −0.065)」→「z = (素点 − μ_場) / σ_場」→「偏差値pt = 50 + 10z」→「寄与 = w_場 × pt」の 4 段を縦に流す。μ・σ・w は右端に置いた weights CSV(場 1 行)から矢印で引く。展示だけは素点の前段に「レース内偏差値化(6 艇)」の箱をもう 1 つ持つ。最下段で 4 つの寄与(+ 第 5 章のモーター)が合流して「強さpt」になる。第 16 章の検算ページ(/lanes/ /racers/ /exhibition/ /weather/)がこの 4 段をそのまま画面に出す、と欄外に添える -->

### 2 種類の標準化

この章には標準化が 2 か所出てきます。混同しやすいので先に整理します。

| 標準化 | 母集団 | μ・σ の出どころ | 使う成分 |
| --- | --- | --- | --- |
| レース内 | 同じレースの 6 艇 | そのレースの値から都度計算 | 展示(素点を作る段階) |
| 場別 | その場の過去 6 か月の全艇 | weights CSV の `mu_*` / `sigma_*` | 4 成分すべて(偏差値pt にする段階) |

展示タイムのような「絶対値がその日の水面や季節で動く量」は、まず同じレースの 6 艇の中で相対位置に直してから場別標準化します。枠番や選手の素点はそれ自体に絶対的な意味があるので、場別標準化だけです。

### `hensachi()`: レース内偏差値

レース内の偏差値化は `index_features.py` の `hensachi()` が担います。本質だけ抜くと次の 15 行です。

```python:hensachi_features.py
import numpy as np

def hensachi(values: list[float]) -> list[float]:
    """6 艇ぶんのタイムを「平均 50・SD 10」に写す。小さいほど高い値になる。"""
    arr = np.array(values, dtype=float)
    valid = ~np.isnan(arr)
    if valid.sum() < 2:                      # 比べる相手がいなければ全艇 NaN
        return [float("nan")] * len(values)
    mean = arr[valid].mean()
    std = arr[valid].std(ddof=0)             # 母標準偏差
    out = []
    for v in arr:
        if np.isnan(v):
            out.append(float("nan"))
        elif std == 0:                       # 全艇同タイムなら差なし
            out.append(50.0)
        else:
            out.append(50.0 + 10.0 * (mean - v) / std)   # 符号が逆
    return out
```

3 つの設計判断が入っています。

- **符号が逆**(`mean − v`)。展示タイムもオリジナル展示も「小さいほど速い」タイムなので、平均より小さい艇が高い偏差値になるようにします。
- **有効値が 2 艇未満なら全艇 NaN**。1 艇しかなければ平均との差が定義できず、その系列は「情報なし」として後段の平均から外れます。
- **σ = 0 なら全艇 50**。6 艇が同タイムなら差はない、という自然な扱いです。0 除算を避けるだけでなく、値として「差なし」を表現しています。

`std(ddof=0)`(母標準偏差)であることは下流の再現に効きます。pandas の `Series.std()` は既定で `ddof=1` なので、fun-site 側で TypeScript に移植するときにここを揃えないと小数第 2 位が合いません。移植時の罠は第 16 章にまとめます。

### 場別標準化と欠損補完

素点を偏差値pt にする最後の段は、`build_index.py` の `_build_one_race_row()` が成分ごとに行います。本質は次の関数です。

```python:hensachi_features.py
def to_hensachi_pt(raw: float, mu: float, sigma: float, w: float, fallback=50.0):
    if np.isnan(raw):
        pt = fallback                        # 欠損補完(選手pt だけ 30)
    else:
        z = (raw - mu) / sigma if sigma > 0 else 0.0
        pt = 50.0 + 10.0 * z
    return round(pt, 2), round(w * pt, 2)
```

`round(pt, 2)` と `round(w * pt, 2)` は、CSV に書く直前の丸めです。寄与は「丸める前の pt」に w を掛けてから丸めるので、CSV の `展示pt × w` を手で計算しても寄与と最下位桁が合わないことがあります。再現するときは同じ順序で丸める必要があります。

## 2. 枠番pt

### 素点: 場 × 季節 × コース別の平均得点

枠番pt の素点は静的テーブル `data/estimate/stadium/win_rate.csv` から引きます。24 場 × 4 季節 = 96 行で、列は `場コード, 季節, 1コース勝率, …, 6コース勝率` です。

```
場コード,季節,1コース勝率,2コース勝率,3コース勝率,4コース勝率,5コース勝率,6コース勝率
01,春,7.702,5.216,5.196,4.72,4.48,2.96
01,夏,7.434,4.87,5.174,5.08,4.62,3.042
```

列名は「勝率」ですが、1 着率(%)ではなく **平均得点**(1 着 10 点〜6 着 1 点の平均)です。値域はおよそ 2.5〜8.4 で、全コース平均が 5 前後になります。季節は 春(3〜5 月)/ 夏(6〜8 月)/ 秋(9〜11 月)/ 冬(12〜2 月)で、`SEASON_BY_MONTH` でレース日の月から引きます。

このテーブルは過去数年ぶんの着順実績から作られた据え置きの静的テーブルで、月次再生成の対象ではなく、生成スクリプトもリポジトリにありません(`docs/data/estimate.md` の Stadium Parameters にその旨が明記されています)。「コースごとの有利不利」は季節より細かい粒度では更新しない、という扱いです。

### 参照するコース: 枠番か実進入か

素点を引くコースが、状態によって変わります。

- `daily`(朝バッチ): 進入はまだ分からないので **枠番** をコースとみなす
- `realtime`(締切 5 分前): スタート展示 `previews/stt` の `艇N_コース` = **実進入コース** で引く

`compute_features_for_day()` は `stt` が無ければ `course = waku` にフォールバックし、`1 ≤ course ≤ 6` でなければやはり枠番に戻します。前づけで進入が入れ替わったレースでは、この切り替えで枠番pt が大きく動きます。

### 検算: 桐生 2026-08-01 1R

2026-08-01 の桐生 1R(レースコード 202608010101)の `daily` 行で確かめます。夏なので `01,夏` の行を使い、桐生の μ = 5.047、σ = 1.365、w = 0.361 を当てると、

| 枠 | 素点(夏・コース別) | z | 枠番pt | 寄与 | index CSV の値 |
| --- | --- | --- | --- | --- | --- |
| 1 | 7.434 | +1.748 | 67.48 | 24.37 | 67.48 / 24.37 |
| 2 | 4.870 | −0.130 | 48.70 | 17.59 | 48.70 / 17.59 |
| 6 | 3.042 | −1.469 | 35.31 | 12.75 | 35.31 / 12.75 |

6 枠すべてで `estimate/v1_basic/2026/08/01.csv` と一致します。枠番pt は素点が静的テーブル、μ/σ/w が weights CSV と、公開されている材料だけで閉じているので、下流でそのまま再現できる成分です。

## 3. 選手pt

### 素点: 着順列をグレード別に得点化する

選手pt の素点は、出走表と一緒に取れる **全国近況 5 節**(`data/programs/recent_national/`)と **当地近況 5 節**(`data/programs/recent_local/`)から作ります。各艇について `艇N_前K節_グレード` と `艇N_前K節_着順列`(K = 1〜5)の組があり、着順列は次のような生文字列です。

```
６　６６５　４２４　３４          ← 一般戦。全角スペースは日区切り
６４５　４６３　６　６            ← ＧⅢ
１２３　Ｆ４　欠　[１]            ← Ｆ は選手責任、欠 は欠場、[１] は優勝戦 1 着
```

得点化の規則は次の通りです(br-racers.jp の能力指数算出式に準拠)。

- 節グレードを **SG・GI / GII / GIII・一般** の 3 段階に丸め、優勝戦かどうかで 6 通りの得点表を引く
- 着順 1〜6 は得点表の値を加算し、出走回数に 1 を足す
- **F / L / 失 / 妨**(選手責任)は **0 点で出走回数だけ足す**。素点を強く下げるペナルティになる
- **欠 / 転 / 落 / 沈 / エ / 不**(欠場や機材トラブル)は集計から外す
- 素点 = 算出基準点合計 ÷ 出走回数 を整数に丸めたもの。出走が 1 回も無ければ NaN

```python:hensachi_features.py
SCORE_TABLE = {
    ("SG_GI", "yusho"): [100, 98, 94, 91, 88, 85],
    ("SG_GI", "other"): [85, 82, 77, 73, 69, 65],
    ("GII",   "yusho"): [80, 78, 74, 71, 68, 65],
    ("GII",   "other"): [70, 67, 62, 58, 54, 50],
    ("GIII",  "yusho"): [65, 63, 59, 55, 52, 50],
    ("GIII",  "other"): [60, 58, 55, 50, 46, 45],
}
ZEN_TO_HAN_DIGIT = {"１": 1, "２": 2, "３": 3, "４": 4, "５": 5, "６": 6}
RACER_RESPONSIBLE_TOKENS = {"F", "L", "失", "妨", "Ｆ", "Ｌ"}      # 分母だけ +1
NOT_RACER_RESPONSIBLE_TOKENS = {"欠", "転", "落", "沈", "エ", "不"}  # 集計除外


def grade_of(grade_str: str) -> str:
    s = (grade_str or "").strip()
    if any(t in s for t in ("ＳＧ", "SG", "ＰＧ", "PG", "ＧⅠ", "GⅠ", "G1", "Ｇ１")):
        return "SG_GI"
    if any(t in s for t in ("ＧⅡ", "GⅡ", "G2", "Ｇ２")):
        return "GII"
    return "GIII"                            # ＧⅢ と一般戦は同じ表


def parse_finishes(seq: str) -> list[tuple[str, bool]]:
    """着順列 → [(トークン, 優勝戦か)]。"[１]" は優勝戦 1 着。"""
    out, i = [], 0
    while i < len(seq):
        ch = seq[i]
        if ch in ("[", "［"):
            j = max(seq.find("]", i + 1), seq.find("］", i + 1))
            if j == -1:                      # 閉じ括弧が無ければ読み飛ばす
                i += 1
                continue
            for c in seq[i + 1:j]:
                if c in ZEN_TO_HAN_DIGIT:
                    out.append((str(ZEN_TO_HAN_DIGIT[c]), True))
            i = j + 1
            continue
        if ch not in (" ", "　"):
            out.append((str(ZEN_TO_HAN_DIGIT.get(ch, ch)), False))
        i += 1
    return out


def racer_pt_for_boat(boat_records: list[tuple[str, str]]) -> float:
    """[(節グレード, 着順列), ...] → 算出基準点合計 ÷ 出走回数(整数丸め)"""
    total_score, total_runs = 0, 0
    for grade_str, seq in boat_records:
        grade = grade_of(grade_str)
        for token, is_yusho in parse_finishes(seq):
            if token in "123456":
                kind = "yusho" if is_yusho else "other"
                total_score += SCORE_TABLE[(grade, kind)][int(token) - 1]
                total_runs += 1
            elif token in RACER_RESPONSIBLE_TOKENS:
                total_runs += 1
    return round(total_score / total_runs) if total_runs else float("nan")
```

得点表は「同じ 1 着でも SG・GI の優勝戦なら 100 点、一般戦なら 60 点」と、グレードと優勝戦で傾斜がついています。相手が強い節での好走ほど高く評価する、という考え方です。

実装(`compute_features_for_day()`)は全国近況と当地近況の `build_recent_records()` の結果を **単純に連結** して `racer_pt_for_boat()` に渡します。当地の節が全国近況の 5 節にも含まれている場合、その節は 2 回計上されます。桐生 1R 1 枠の例では、10 レコードのうち桐生 2026-05-01〜06 の節が両方に載っていました。良し悪しは別として、下流で再現するときはこの挙動もそのまま写す必要があります(第 16 章)。

### 検算: 桐生 2026-08-01 1R 1 枠

上の関数に桐生 1R 1 枠の 10 レコードを通すと素点は 48 になります。桐生の μ = 53.79、σ = 4.958 で z = −1.168、選手pt = 38.32、w = 0.2246 で寄与 = 8.61。index CSV の `1枠_選手pt` = 38.32、`1枠_寄与_選手pt` = 8.61 と一致します。6 枠すべてで一致することも確認しました。

### 欠損補完が 50 ではなく 30 の理由

素点が NaN になるのは、近況 10 節に有効な出走が 1 回も無いときです。新人や長期離脱明けがほとんどで、こういう選手を「平均並み(50)」とみなすと過大評価になりやすい。そこで選手pt だけは **30**(平均より 2σ 下)で補完します。この補完値は `registry.py` の `COMPONENT_MISSING_FALLBACK` で成分ごとに一元管理されていて、現状 `racer` 以外は既定値の 50 です。

```python
COMPONENT_MISSING_FALLBACK: Mapping[str, float] = {
    "racer": 30.0,
}
COMPONENT_MISSING_FALLBACK_DEFAULT: float = 50.0
```

「欠損は平均で埋める」は機械学習の定石ですが、**欠損すること自体に情報がある**なら平均は正しい補完値ではありません。ここでは欠損サンプルが実力下位に偏るという事実に合わせて補完値を下げています。

参考までに、2026 年 8 月の `v1_basic` の `daily` 行 29,520 艇(= 4,920 レース × 6 艇)を数えると、選手pt が 30.00 ちょうどの艇は 0 でした。フォールバックが効く場面は稀ですが、効いたときの影響が大きいので値を決めておく、という位置づけです。

## 4. 展示pt

### 素点: 4 系列のレース内偏差値の等重み平均

展示pt は **その日の直前情報だけで閉じている**成分です。入力は `data/previews/` の 2 ファイル、4 系列です。

| 系列 | ソース | 列 |
| --- | --- | --- |
| 展示タイム | `previews/tkz/YYYY/MM/DD.csv` | `艇N_展示タイム` |
| オリジナル展示 1〜3 | `previews/original_exhibition/YYYY/MM/DD.csv` | `艇N_値1` / `艇N_値2` / `艇N_値3`(項目名は `計測項目1〜3`。多くの場で 一周 / まわり足 / 直線) |

手順は 3 段です。

1. **レース内偏差値**。系列ごとに 6 艇まとめて `hensachi()` にかける(符号反転、2 艇未満は NaN、σ = 0 は 50)
2. **等重み平均 → 素点**。`raw = round(mean(NaN でない z_k), 2)`。項目別の重みは**存在しない**
3. **場別標準化 → 展示pt**。`展示pt = round(50 + 10 × (raw − mu_exhibit) / sigma_exhibit, 2)`、`寄与 = round(w_exhibit × 展示pt, 2)`

```python:hensachi_features.py
def exhibit_raw(exhibit_times: list[float], orig: dict[int, list[float]]) -> list[float]:
    """exhibit_times: 艇1..6 の展示タイム。orig: {艇番: [値1, 値2, 値3]}"""
    series = [
        hensachi(exhibit_times),
        hensachi([orig[i][0] for i in range(1, 7)]),
        hensachi([orig[i][1] for i in range(1, 7)]),
        hensachi([orig[i][2] for i in range(1, 7)]),
    ]
    out = []
    for i in range(6):
        zs = [s[i] for s in series if not np.isnan(s[i])]
        out.append(round(sum(zs) / len(zs), 2) if zs else float("nan"))
    return out
```

素点がレース内偏差値の平均なので、素点の場別平均 `mu_exhibit` は 50 のすぐ近く(2026-08 の weights では 24 場で 49.99〜50.02)、`sigma_exhibit` は 6〜7 前後(24 場で 5.57〜10.00)になります。場別標準化はここでは「平均を揃える」よりも「レース内でのばらつきの大きさを場の水準に揃える」役割を果たしています。

### 場によって系列数が違う

等重み平均は「系列数が場によって違う」ことを吸収します。

- **江戸川 (03)** はオリジナル展示の配信が無く、展示タイムの 1 系列だけ
- **住之江 (12) / 尼崎 (13) / 徳山 (18)** は `計測数=2`(`値3` が空)で 3 系列
- **桐生 (01)** は `計測項目1` が「一周」ではなく「半周ラップ」。項目名が違うだけで扱いは同じ
- 4 系列すべて NaN(展示タイムも欠測)の艇は素点 NaN → 展示pt 50 で補完

項目ごとに重みを学習しないので、系列がいくつあっても同じ式で済み、下流が再現するのに必要なのは weights CSV の `mu_exhibit` / `sigma_exhibit` / `w_exhibit` の 3 列だけになります。江戸川の `w_exhibit` は 2026-08 の weights で 0.055 と他場(0.17〜0.26)より小さいのですが、これは 1 系列しか無いぶん素点の情報量が少ないためと考えられます。

:::message
スタート展示 ST(`previews/stt`)は展示pt の入力では**ありません**。`stt` から読むのは進入コースだけで、枠番pt・気象pt がそれを使います。展示 ST・体重・チルトはどの成分にも入っていません。
:::

### fun-site が再現できるように手順を明文化した経緯

配信側の fun-site には、成分ごとに「素点 → 偏差値pt → 寄与」を実値で展開する検算ページがあります(第 16 章)。2026-08-23 までは展示詳細ページが展示pt を「再現不可」と表示し、しかも「展示 ST も重み付けしている」という誤った説明を出していました。

実際には、展示pt の素点は上の手順だけで決まり、外から必要なのは場別の μ/σ/w だけ。しかもその 3 列は fun-site が枠番pt・気象pt のために既に取得していた weights CSV に入っていました。そこで `docs/data/estimate.md` に「展示pt の算出手順(fun-site 再現用)」の節を追加し、fun-site 側は weights から `exhibit` 成分を切り出してレース JSON に焼き込むだけで済ませました。上流の配信物は変更していません。2026-07〜08 の実データ 49,092 艇で index CSV と小数第 2 位まで一致することを確認し、代表 5 レースをテストのゴールデンとして固定しています(fun-site `docs/architecture.md` 2026-08-23)。

この「再現できないと思っていたものが、手順を書き出したら再現できた」という出来事は、特徴量関数の仕様を **コードとは別に文章で持つ**ことの価値を示しています。章末の演習で、読者にも同じ再現を試してもらいます。

## 5. 気象pt

### 素点: 線形回帰係数 × 当日気象

気象pt は、当日の水面気象からコースごとの有利不利を計算した値です。入力は `previews/sui/YYYY/MM/DD.csv` の 6 列(風速・風向・波の高さ・天候・気温・水温)で、係数は `data/estimate/stadium/sui_params.csv` にあります。1 場 1 行、43 列(`stadium` + 切片 6 + 6 特徴量 × 6 コース)です。

| 列グループ | 内容 |
| --- | --- |
| `base_c1〜c6` | 基準条件(凪・無風・晴・気温 = 水温)下の有利pt切片。**index 計算では使わない** |
| `wave_cm_c1〜c6` | 波高 1 cm あたりの有利pt変化 |
| `temp_diff_c1〜c6` | 気温 − 水温 1 ℃ あたりの有利pt変化 |
| `wind_tail_ms_c1〜c6` | 追い風 1 m/s あたりの有利pt変化 |
| `wind_head_ms_c1〜c6` | 向かい風 1 m/s あたりの有利pt変化 |
| `is_cloudy_c1〜c6` | 曇り(vs 晴)による有利ptシフト |
| `is_rainy_c1〜c6` | 雨(vs 晴)による有利ptシフト |

当日気象から 6 次元の特徴量ベクトルを作り(`weather_features()`)、コース c の素点は `feats · coefs[c]` の内積です(`weather_advantage()`)。CSV には `round(…, 4)` した値が入ります。

### 風向を場の向きで正規化する

風向は `sui` に 1〜8 のコードで入っていて、`WIND_CODE_TO_DEG` で 45° 刻みの角度に直します。ただし「北風」が有利か不利かは場の向きで変わるので、場ごとの `facing_deg`(`STADIUM_FACING`。桐生 90、戸田 0、江戸川 200 など)との相対角で **追い風 / 向かい風 / 横風** に分けます。

```
rel = (wind_deg − facing_deg) mod 360
追い風  : rel < 45 または rel ≥ 315   → wind_tail_ms = 風速、wind_head_ms = 0
向かい風: 135 ≤ rel < 225             → wind_tail_ms = 0、wind_head_ms = 風速
横風    : それ以外                    → 両方 0
```

天候コードは `WEATHER_CODE_TO_LABEL` で 晴 / 曇 / 雨 の 3 値に落とします(雪・霧に相当するコード 4・5 は雨扱い)。気温か水温が欠けている場合は気象そのものを None とし、気象pt は 50 で補完されます。

### 切片を使わない理由

`base_c1〜c6` は「基準条件でのコース固定の有利」で、1 コースが大きく、6 コースが小さい。これは枠番pt(場 × 季節 × コース別の平均得点)とほぼ同じ情報です。両方を成分に入れると相関 0.98 以上の多重共線性が起き、重み学習(第 7 章)が不安定になります。そこで気象pt は **切片を除いた変動分だけ** を返し、コース固定の有利は枠番pt に集約しています。素点の場別平均 `mu_weather` が 24 場すべてで ±0.001 以内(2026-08)なのはこのためです。

### 検算: 三国 2026-08-01 1R

三国 1R(202608011001)の `sui` 行は 風速 2.0 m / 風向コード 4(135°)/ 波 2 cm / 天候 2(曇)/ 気温 27 ℃ / 水温 28 ℃ でした。三国の `facing_deg` は 270 なので rel = 225 で横風、特徴量は `[wave=2, temp_diff=−1, tail=0, head=0, cloudy=1, rainy=0]` です。三国の係数と内積を取り、μ = −0.00004、σ = 0.1019、w = 0.0804 で標準化すると次のようになります。

| コース | 素点 | 気象pt | index CSV(realtime) |
| --- | --- | --- | --- |
| 1 | −0.0650 | 43.63 | 43.63 |
| 2 | −0.0226 | 47.79 | 47.79 |
| 3 | +0.1975 | 69.38 | 69.38 |
| 4 | +0.0610 | 55.99 | 55.99 |
| 5 | −0.0699 | 43.15 | 43.15 |
| 6 | −0.1010 | 40.10 | 40.10 |

素点の絶対値は 0.1 程度と小さいのですが、σ も 0.1 程度なので、偏差値にすると 40〜70 の幅に広がります。このレースでは曇りの係数(`is_cloudy_c3` = +0.164)が 3 コースの気象pt を押し上げています。

係数の学習は `scripts/build_sui_params.py` で実データから再実行できます。場ごとの R² は概ね 0.05〜0.20 で、気象だけで着順を説明できる範囲は小さい。それでも成分として残しているのは、寄与の重み `w_weather` を場ごとに学習させれば、波が立ちやすい場では大きく、そうでない場では小さく効く形で使い分けられるからです(第 7 章)。

## 6. daily と realtime で何が変わるか

`build_index.py` は 1 レースにつき最大 2 行を書きます。状態列 `状態` が `daily` と `realtime` です。

| 状態 | いつ | 枠番pt | 選手pt | モーターpt | 展示pt | 気象pt |
| --- | --- | --- | --- | --- | --- | --- |
| `daily` | 朝 07:30 JST の日次バッチ | 枠番基準 | 実値 | 実値 | **50 固定** | **50 固定** |
| `realtime` | 締切 5 分前の直前バッチ | **実進入コース**基準 | 実値(再計算、同じ値) | **daily の値を引き継ぐ** | 実値 | 実値 |

### 中立値で固定する成分

朝の時点では展示も気象も存在しないので、`DAILY_NEUTRAL_COMPONENTS` に列挙された成分は素点があってもなくても偏差値pt = 50 に固定されます。寄与は `50 × w` になり、`daily` 行では全艇が同じ値です。

```python
DAILY_NEUTRAL_COMPONENTS: frozenset[str] = frozenset({"exhibit", "weather", "tenkai"})
```

`_build_one_race_row()` は `skip_preview=True` のとき、これらの成分の `raw → z → pt` を飛ばして 50 を入れます。桐生 1R の `daily` 行で `1枠_寄与_展示pt` が 10.57 = 50 × 0.2115 になっているのはこのためです。`tenkai` は退役した `v2_tenkai` の展開優位pt で、進入コースに依存するので同じ扱いです。

### 引き継ぐ成分

逆に `realtime` で再計算 **しない** 成分もあります。

```python
DAILY_REUSED_COMPONENTS: frozenset[str] = frozenset({"motor", "motor4"})
```

モーターpt の素点は当場の直近 6 節 = 過去 90 日ぶんの出走表を舐めて作りますが(第 5 章)、2 分毎に走る直前バッチのジョブは当月ぶんしか checkout していません。そのまま再計算すると月初で採用節数が 0〜1 節に落ち、`daily` 行と `realtime` 行でモーターpt が食い違います。モーターpt は当日中に変化しない量なので、`realtime` 行は `daily` 行の偏差値pt をそのまま使います(`_daily_reuse_pts()` が `(枠番, 成分)` → pt の辞書を作り、`reuse_pt` として渡す)。`daily` 行が無い場合だけ再計算にフォールバックします。

### 切り替わる成分

枠番pt は素点を引くコースが枠番から実進入コースに変わるので、進入が入れ替わったレースでは値が変わります。選手pt は入力が近況 CSV だけなので、再計算しても同じ値になります。

### 行の扱い

`update_index_for_races()` は既存 CSV を読み、対象レースの `realtime` 行を **追加または置換** します。`daily` 行は上書きも削除もされず、レースコード昇順・daily → realtime の順で並べ直して原子的に書き戻します。直前バッチが 2 回走っても行数は増えません。`daily` 行を残すことで、朝の時点の予想(当日買い目)と直前の予想(直前買い目)の両方が保存され、fun-site はその両方を表示します。展示pt と気象pt が 50 固定から実値に変わることが、当日買い目と直前買い目が変わる主因のひとつです。

なお、weights CSV が見つからない月(その予想者の初月など)は、全成分が NaN で出力されます。重みのブートストラップは第 7 章で扱います。

## 元資料

- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md (Strength Index の列の詳細説明、補完ルール、展示pt の算出手順、Stadium Parameters)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/index_features.py (`hensachi()`、`waku_pt()`、`racer_pt_for_boat()`、`weather_features()`、`compute_features_for_day()`)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_index.py (`DAILY_NEUTRAL_COMPONENTS`、`DAILY_REUSED_COMPONENTS`、`_build_one_race_row()`)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py (`COMPONENT_MISSING_FALLBACK`)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/data/estimate/stadium/win_rate.csv 、 https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/data/estimate/stadium/sui_params.csv
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md 、 https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md (入力 CSV の列定義)
- https://github.com/BoatraceCSV/fun-site/blob/main/docs/architecture.md (2026-08-23 の展示pt 再現対応)

## 演習

1 日分の `previews/tkz` と `previews/original_exhibition` から展示pt を自分で計算し、`estimate/v1_basic` の `realtime` 行の `N枠_展示pt` / `N枠_寄与_展示pt` と一致することを確かめてください。必要なファイルは 4 つで、すべて公開 CSV です。

```bash
BASE=https://boatracecsv.github.io/data
curl -sO $BASE/previews/tkz/2026/08/01.csv
curl -sO $BASE/previews/original_exhibition/2026/08/01.csv
curl -sO $BASE/estimate/stadium/weights/v1_basic/2026-08.csv
curl -sO $BASE/estimate/v1_basic/2026/08/01.csv
```

手順は §4 の 3 段そのままです。レースコードで `tkz` と `original_exhibition` を引き、`exhibit_raw()` で素点を作り、レースコード 9〜10 桁目の場コードから場名を引いて weights の `mu_exhibit` / `sigma_exhibit` / `w_exhibit` で標準化します。比較対象は `状態=realtime` の行だけです(`daily` 行は 50 固定)。

本書の簡略版コードで実際に試した結果は次の通りです。

| 日付 | realtime レース数 | 艇数 | 一致(小数第 2 位まで) | 不一致 |
| --- | --- | --- | --- | --- |
| 2026-08-01 | 156 | 936 | 936 | 0 |
| 2026-08-09 | 168 | 1,008 | 1,008 | 0 |

2026-08-09 は江戸川(オリジナル展示なし、1 系列)と住之江(`計測数=2`、3 系列)の両方が開催日に含まれていて、系列数が違う場でも同じ式で一致することが確認できます。もし手元で差が出た場合は、(1) 標準偏差が `ddof=0` になっているか、(2) 素点を `round(…, 2)` してから標準化しているか、(3) 寄与を「丸める前の pt × w」から計算しているか、(4) weights が対象月以下で最新のファイルか、の 4 点を疑ってください。

発展として、同じ日の枠番pt(`win_rate.csv` + `previews/stt` の実進入コース)と気象pt(`previews/sui` + `sui_params.csv`)も再現してみてください。4 成分のうちこの 3 つは公開 CSV だけで閉じています。
