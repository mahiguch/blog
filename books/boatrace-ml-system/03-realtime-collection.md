---
title: "直前情報とリアルタイム収集"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 「締切前に取れる情報」の境界。展示タイム・進入コース・気象は締切の約 10 分前にしか揃わず、その時刻を行に刻んでおくことが、後の学習でリーク(未来の情報の混入)を防ぐ唯一の手段になる |
| システム | 2 分毎に走るジョブの設計、開催一覧 JSON からの締切窓の判定、固定窓をやめたキャッチアップモード、データソースごとの CSV 分割、結果と払戻の独立 append、daily / realtime の状態列 |

第 2 章では、公式サイトの日次ファイルから「1 レース 1 行」の CSV を作りました。
その CSV には出走表と確定結果が入りますが、予想に効く情報の多くは**レース直前**にしか公開されません。
展示航走のタイム、スタート展示で見せた進入コース、その時刻の風と波です。
これらは日次ファイルには載らず、`race.boatcast.jp` が締切前の短い時間だけ配信する TSV から拾うしかありません。

この章は、その直前情報を 2 分毎のジョブで取り続ける仕組みの話です。
毎日 8 時から 23 時まで、開催中の全レースについて「今どのレースを取るべきか」を判定し、
取れたものだけを追記し、取れなかったものは次のサイクルで拾い直します。
派手な機械学習は出てきませんが、第 4 章以降の特徴量はすべてここで集めた行の上に立っています。

## 1. 直前情報とは何か

### 1.1 4 つのデータソース

`race.boatcast.jp` は、公式サイトの SPA が描画に使う TSV ファイルを CloudFront 経由でそのまま配信しています。
認証は不要で、URL の規則さえ分かれば `requests.get` で取れます。直前情報として使うのは次の 4 ソースです。

| ソース | ファイル | 内容 | 追記できる条件 |
| --- | --- | --- | --- |
| `tkz` | `hp_txt/{場}/bc_j_tkz_{日付}_{場}_{R}.txt` | 6 艇の展示タイム、体重、体重調整、チルト | `status == "1"`(計測済み)。`"0"` は計測中、`"2"` は計測不能 |
| `stt` | `hp_txt/{場}/bc_j_stt_{日付}_{場}_{R}.txt` | 6 艇の進入コースとスタート展示 ST(F は負値、L は空欄) | ファイルが存在する |
| `sui` | `m_txt/{場}/bc_sui_{日付}_{場}.txt` | 場ごとの最新の水面気象(風速、風向、波高、天候、気温、水温) | ファイルが存在する。レース単位ではなく場単位 |
| `original_exhibition` | `txt/{場}/bc_oriten_{日付}_{場}_{R}.txt` | 場ごとに 2〜3 項目のオリジナル展示(一周、まわり足、直線 など) | `status == "1"` かつ 6 艇そろっている。江戸川は配信自体がない |

ファイルは `data/previews/{ソース}/YYYY/MM/DD.csv` に 1 レース 1 行で追記され、
どのファイルも先頭 6 列は共通です。

```
レースコード, レース日, レース場, レース回, 締切時刻, 取得日時
```

`レースコード`(`YYYYMMDDjjrr`)が第 2 章と同じ主キーなので、出走表とも結果とも `merge` 一発で結合できます。
`取得日時` は JST の ISO 8601(例 `2026-08-01T08:22:26+09:00`)で、
「この行の値は、この時刻に公開されていたものである」という保証を担います。

同じ仕組みに後から乗った派生ソースが 4 つあります。
集計中オッズ `od1` / `od2` / `od3`(3 連単 120 通りなどの締切前スナップショット)と、得点率早見 `tokuten_hayami` です。
締切窓の判定、ソースごとの dedup、日次 CSV のレイアウトはすべて共通で、
コード上は `PREVIEW_SOURCES + ODDS_SOURCES` のタプルに名前を足しただけです。
本章では設計の核になる 4 ソースを中心に話を進めます。

:::message
boatcast の TSV には「無いファイル」の表現が 2 通りあります。HTTP 403/404 を返す場合と、
HTTP 200 で SPA の HTML を返す場合(CloudFront のフォールバック)です。
すべてのフェッチャーが、本文の先頭が `<` なら欠損として扱うようにしています。
ステータスコードだけを見ていると、HTML をパースしようとして静かに空行を書く事故になります(第 12 章)。
:::

### 1.2 なぜソースごとに CSV を分けるか

4 ソースを 1 行にまとめた「直前情報 CSV」を作るほうが、使う側は楽に見えます。
それでも分けた理由は 3 つあります。

1. **公開タイミングが違う。** 展示タイムは計測中(`status=0`)の時間があり、スタート展示はさらに後に出ます。
   1 行にまとめると「全部そろうまで書けない」か「一部が空欄の行を後で書き直す」かのどちらかになり、
   追記専用(append-only)の単純さを失います。
2. **気象は時間変化そのものに意味がある。** `sui` は場単位の最新値なので、
   同じ場の 1R と 12R では別の値になります。レースごとに取得時刻つきで残しておけば、
   後から「風が強まった日の後半レース」のような分析ができます。
3. **下流がそのまま読める。** 第 4 章の特徴量関数 `index_features.py` は、
   `tkz` から展示タイム、`original_exhibition` から 3 項目、`stt` から実進入コース、`sui` から気象を、
   それぞれ別のファイルとして読みます。中間形式を挟まないので、変換層のバグが入り込む余地がありません。

### 1.3 「締切前に取れる情報」の境界

機械学習の観点で、この章で一番大事なのは `取得日時` 列です。
学習データを作るとき、「レース前に知り得た情報」だけを特徴量にしないと、
モデルは本番では手に入らない情報を頼りに高い精度を出してしまいます。
展示タイムは締切前に公開されるので特徴量にしてよく、決まり手は結果なので特徴量にしてはいけません。
境界が曖昧なのは気象で、`bc_rs1_2`(結果ファイル)の末尾にも気象行がありますが、
これはレース後の記録です。締切前の予想に使えるのは `sui` の値だけです。

では実際に、どのくらい前に取れているのでしょうか。
公開 CSV の `締切時刻` と `取得日時` の差を 2026 年 8 月の 1 か月分で測ると、
`stt` は締切の**中央値 9.3 分前**(n = 4,757 レース、10 パーセンタイル 8.4 分前、90 パーセンタイル 9.6 分前)でした。
`tkz` / `sui` / `original_exhibition` もほぼ同じ分布です。
資料では「締切 5 分前のスナップショット」と表現していますが、
次節の窓 `[now+1 分, now+10 分]` に 2 分刻みのサイクルが最初に当たる時刻が 8〜10 分前になるためです。
`stt` の最小値は 1.3 分前で、これは最初のサイクルでファイルが未公開だったレースを、窓の中で再試行し続けて拾ったものです。

## 2. 締切窓の判定

### 2.1 開催一覧 JSON

「今どのレースを取るべきか」を知るには、今日どの場が開催していて、各レースの締切が何時かが要ります。
これも boatcast の SPA が使う JSON `api_txt/getHoldingList2_{YYYYMMDD}.json` にあります。
場ごとに 12 レース分の締切時刻 `DeadlineTimeAll`、中止状態 `CancelStatusAll`(空文字 / 順延 / 中止 / 途中中止)が並んでいるので、
`holding_list.py` はこれを `HoldingRace(stadium_code, race_number, deadline_time, cancel_status, title)` の平坦なリストに展開します。
この JSON 自体は保存しません。毎サイクル取り直します。

ひとつ癖があります。締切を過ぎたレースの `DeadlineTimeAll` は `"HH:MM"` から `"締切"`、
さらに `"確定"` へと**書き換わります**。
つまりライブの一覧からは「終わったレースの締切が何時だったか」が分からなくなります。
締切前のレースを選ぶ分には問題ありませんが、締切後のレースを扱う結果パス(第 3 節)では、
朝の日次バッチが `data/programs/title/YYYY/MM/DD.csv` に写しておいた `電話投票締切予定` を代わりに使います。
`load_holding_from_title_csv()` がそのフォールバックで、title CSV が無い日だけライブの一覧に戻ります。

### 2.2 窓 [now+1 分, now+10 分]

対象レースの条件は 3 つです(`select_eligible_races`)。

- `cancel_status` が空(中止・順延・途中中止でない)
- 締切時刻が `[now + window_min, now + window_max]` に入る。既定は `window_min=1`、`window_max=10`
- レースコードが**すべての**ソース CSV に記録済みではない

3 つ目は積集合ではなく「全部そろって初めてスキップ」です。
`tkz` は書けたが `stt` はまだ、というレースは次のサイクルでも対象に残り、
各ソースの追記処理が自分の CSV だけを見て dedup します(`already_recorded[src]`)。
これが部分的な成功を次のサイクルで自然に完成させる仕組みで、第 4 節の「独立 append」と同じ考え方です。

窓の幅が 9 分もあるのは、もともと GitHub Actions の cron で動かしていた名残です。
GitHub Actions の `schedule:` は混雑時に間引かれ、5 分粒度のつもりが実質 1 時間に 1 回しか発火しないことがありました。
そこで窓を広く取り、多少遅れて発火しても取りこぼさないようにしていました。
現在は Cloud Scheduler(`*/2 8-22 * * *`、Asia/Tokyo)から Cloud Run Jobs を直接叩く構成(第 11 章)で、
JST 08:00〜22:58 に 2 分毎、1 実行のタイムアウトは 300 秒です。
2 分刻みになった今も窓は変えていません。ファイルが未公開(`status=0`)だったレースを、
締切 1 分前まで 2 分おきに再試行できるからです。

![1 サイクルの流れと締切窓](/images/boatrace-ml-system/03-realtime-cycle.png)
<!-- 図: 横軸を時刻にしたタイムライン。あるレースの締切 D を中心に、左側に preview 窓 [now+1, now+10](D の 10〜1 分前)、右側に結果パスの開始点 D+3 分と「終日再試行」の矢印を描く。2 分刻みのサイクル(●)を並べ、最初に窓へ入ったサイクルで tkz/stt/sui/oex を取得、status=0 なら次の●で再試行、D+3 以降の●で bc_rs1_2 / bc_rs2 を独立に取得、という流れを示す -->

### 2.3 1 実行 4 パス、1 コミット

1 サイクル(`preview-realtime.py` の 1 回の実行)は次の順で進みます。

1. 開催一覧 JSON を取得する
2. **preview パス**: 窓に入ったレースについて `tkz` / `stt` / `sui` / `original_exhibition`(と得点率早見)を取得し、ソースごとの CSV に追記する
3. **odds パス**: 同じ対象レースについて `od1` / `od2` / `od3` を取得し追記する
4. preview 行が追記されたレースについて、active な全予想者の index CSV(`data/estimate/{predictor_id}/`)の `状態=realtime` 行を更新する(第 2.4 節)
5. **result パス**: 締切から 3 分以上経った未記録レースについて `bc_rs1_2` を取得し `data/results/realtime/` に追記する
6. **payout パス**: 同じ条件で `bc_rs2` を取得し `data/results/payouts/` に追記する
7. 追記があったファイルだけを 1 コミットにまとめて push する
8. 変更のあった CSV を GCS にミラーし、Pub/Sub にレースコードの集合を publish する(第 13 章で fun-site がこれを受けます)

コミットメッセージは `Update realtime: 2026-07-28 [preview 11-07,23-05 | result 11-06 | payout 11-06]` のような形で、
どのパスがどのレースを書いたかが履歴から追えます。追記が 0 行なら何もせず終了します。

4 つのパスを 1 つのジョブにまとめているのは、Cloud Scheduler の無料枠(3 ジョブ)という現実的な理由に加えて、
「同じ開催一覧、同じ `now`、同じレートリミッタ」を共有できるからです。
直前ジョブは 1 サイクルを 2 分に収める必要があるため、第 2 章の日次収集(3 秒間隔)と違って
`RateLimiter` の間隔は設定値(既定 0.1 秒)にしています。
`sui` は場単位のファイルなので、同じ場の複数レースが窓に入っても 1 サイクル内では 1 回しか取りません(`sui_cache`)。

### 2.4 daily と realtime の「状態」列

ここで、第 4 章以降で繰り返し出てくる**状態列**を導入しておきます。

強さポイントを持つ index CSV(`data/estimate/{predictor_id}/YYYY/MM/DD.csv`)は、
朝 7:30 の日次バッチが当日の全レース分を `状態=daily` で書きます。
この時点では展示も気象もまだ無いので、展示pt と気象pt は偏差値 50(平均)で埋めます。
これが第 4 章の `DAILY_NEUTRAL_COMPONENTS` です。
直前ジョブが preview 行を追記すると、そのレースについて成分を再計算し、
`状態=realtime` の行を**追加**します。`daily` 行は消しません。
同じレースの `realtime` 行が既にあれば(2 サイクル目以降)、その行だけを差し替えます。
`build_index.update_index_for_races()` がこの upsert を担い、キーは `(レースコード, 状態)` の組です。

つまり同じレースが index CSV に最大 2 行あり、fun-site は `daily` を「当日買い目」、`realtime` を「直前買い目」として別々に表示します。
回収率の集計母数になるのは `realtime` 行だけです(第 9 章)。
preview CSV は「レースコードで dedup した追記専用」、index CSV は「(レースコード, 状態) で upsert」と、
ファイルの性格によって更新規則を変えていることを覚えておいてください。

## 3. 結果の取りこぼしとキャッチアップモード

### 3.1 結果パスの当初の設計

結果ファイル `bc_rs1_2` は、着順、決まり手、進入コース順の実測 ST、レース後の気象を持ちます。
締切後すぐには存在せず、レースが確定してから公開されます。
当初の結果パスは、締切から `[3 分, 30 分]` 経ったレースだけを候補にする固定窓でした。
下限の 3 分は「それより前に見ても必ず 403」だから、
上限の 30 分は「それ以降は書き終わっているはずで、無駄な HTTP を減らしたい」からです。
冪等性はレースコードの dedup で守られているので、上限は純粋にトラフィックの節約でした。

### 3.2 2026-07-28 びわこ

2026 年 7 月 28 日、びわこの SG オーシャンカップ初日は、進行が予定締切より 13〜48 分遅れました。
7R の締切は 13:48 でしたが結果が記録されたのは 14:01 以降、8R は締切 14:20 に対して 15:08 です。
固定窓 `[締切+3, 締切+30]` は、`bc_rs1_2` が公開される前に閉じてしまいました。
7R から 12R までの 6 レース(と津の 10R)は、その日一度も候補にならず、CSV に行がないまま夜を迎えました。

失敗が「沈黙」していたことに注意してください(第 12 章)。
ジョブは毎サイクル正常終了していました。
403 は想定内としてスキップし、窓から外れたレースは候補にすら上がらないので、ログにも何も出ません。
気づいたのは、fun-site の的中率集計に当日のびわこ後半が無かったからです。
当日 23 時前に手動で 6 レース分を追記し(公開 CSV の 7R〜12R の `取得日時` が
すべて `22:59:13` なのはこのためです)、同じコミットで結果パスの設計を変えました。

### 3.3 固定窓をやめる

修正は `select_finished_races()` の 3 点です。

1. **上限を無くす。** `--result-window-max` の既定を `30` から `None` にし、
   未記録のレースは締切から 3 分経った後ずっと候補に残す(キャッチアップモード)。
   明示的に整数を渡せば従来の固定窓に戻せます
2. **締切の古い順に並べ、1 回あたり 15 件で打ち切る**(`--result-catchup-limit`、`0` で無制限)。
   障害の後に溜まった何十レースかを 1 回で全部取りに行くと、Cloud Run Jobs の 300 秒タイムアウトに当たります。
   2 分毎のサイクルで 15 件ずつ消化すれば、バックログは自然に解消します
3. **締切時刻は title CSV から引く。** 第 2.1 節のとおり、ライブの開催一覧は締切後のレースの時刻を消してしまうので、
   キャッチアップの候補が終日残るためには、朝に写した締切が必要です

コストは、確定しなかったレース(途中中止など)についても、その日の終わりまで 2 分おきに 403 を受け続けることです。
1 リクエストで済み、件数も 15 に抑えられているので許容しました。

効果は数字で見えます。2026 年 8 月の `data/results/realtime/` は 4,798 行で、
`取得日時` は締切の**中央値 17.4 分後**、90 パーセンタイルで 22.4 分後でした。
30 分を超えて取得された行は **185 件(3.9%)**あり、旧固定窓ならこれらは永久に欠けていました。
払戻(`data/results/payouts/`、4,797 行)は結果より早く、中央値 9.4 分後です。

:::message alert
「上限を無くす」は、窓を `[3 分, 120 分]` に広げる案より単純で、かつ正しい選択でした。
どれだけ広げても「それを超える遅延」は起き得ますし、広げた分だけ毎サイクルの候補が増えます。
未記録である限り候補に残し、件数で打ち切るほうが、遅延の分布を仮定せずに済みます。
:::

## 4. 結果と払戻を独立に append する

結果 `bc_rs1_2` と払戻 `bc_rs2` は、boatcast が別々に公開します。
通常は数秒差ですが、片方だけ存在する瞬間があります。
そこで両方が揃うのを待たず、それぞれの CSV について「自分のファイルに無いレースコード」だけを候補にし、取れたものだけを追記します。

```
result パス:  candidates = 未記録(results/realtime) ∧ 締切+3 分経過 → bc_rs1_2 を取得 → append
payout パス:  candidates = 未記録(results/payouts)  ∧ 締切+3 分経過 → bc_rs2   を取得 → append
```

あるサイクルで結果だけ取れたレースは、次のサイクルの payout パスで払戻だけが候補に残ります。
「揃うまで待つ」設計と比べると、状態を持たない(ファイルの有無がそのまま状態)、
片方の障害がもう片方を巻き込まない、部分成功が次のサイクルで自動的に完成する、という利点があります。
欠点は、ある瞬間に結果はあるが払戻がない行が存在し得ることですが、
下流は `レースコード` で JOIN するだけなので、揃っていないレースは単に結合から落ちます。

これは preview パスの per-source dedup(第 2.2 節)、オッズ 3 ファイルの独立取得、
そして GCS ミラーや Pub/Sub の失敗を git push の成否に影響させない方針(次サイクルで補える)まで、
このジョブ全体を貫く原則です。**取れたものだけを書き、書けなかったものは次に回す。**
2 分毎に必ず次が来ることが、この単純さを支えています。

## 5. 簡略版コード

締切窓の判定と、レースコードで dedup して追記する関数を、実装から本質だけ抜き出したものです。
関数名と既定値は実装(`preview-realtime.py`、`preview_csv.py`、`holding_list.py`)に合わせています。
実装では dedup を呼び出し側(`existing_race_codes` を先に引く)で行い、`append_rows` は書くだけですが、
ここでは 1 関数にまとめています。

```python:realtime_window.py
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
SOURCES = ("tkz", "stt", "sui", "original_exhibition")


@dataclass
class HoldingRace:
    stadium_code: int
    race_number: int
    deadline_time: str   # "HH:MM"。締切後は "締切" / "確定" に書き換わる
    cancel_status: str   # "" | "順延" | "中止" | "途中中止"

    @property
    def is_open(self) -> bool:
        return self.cancel_status == ""


def build_race_code(date_str: str, stadium_code: int, race_number: int) -> str:
    return f"{date_str.replace('-', '')}{stadium_code:02d}{race_number:02d}"


def deadline_to_jst_datetime(date_str: str, deadline: str) -> datetime | None:
    hh, _, mm = deadline.partition(":")
    if not (hh.isdigit() and mm.isdigit()):   # "締切" / "確定" は None
        return None
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST)
    return base.replace(hour=int(hh), minute=int(mm))


def select_eligible_races(
    races: list[HoldingRace], now_jst: datetime, date_str: str,
    window_min: int, window_max: int, already_recorded: dict[str, set[str]],
) -> list[HoldingRace]:
    """締切が [now+window_min, now+window_max] 分に入り、未記録のソースが残るレース。"""
    lower = now_jst + timedelta(minutes=window_min)
    upper = now_jst + timedelta(minutes=window_max)
    eligible = []
    for race in races:
        if not race.is_open:
            continue
        deadline_dt = deadline_to_jst_datetime(date_str, race.deadline_time)
        if deadline_dt is None or not (lower <= deadline_dt <= upper):
            continue
        race_code = build_race_code(date_str, race.stadium_code, race.race_number)
        # 全ソースに揃って初めてスキップ。1 つでも欠けていれば再対象にする
        if all(race_code in already_recorded.get(src, set()) for src in SOURCES):
            continue
        eligible.append(race)
    return eligible


def existing_race_codes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)                     # ヘッダ
        return {row[0] for row in reader if row}


def append_rows(path: Path, headers: list[str], rows: list[list[str]]) -> int:
    """レースコード(先頭列)で dedup してから追記する。戻り値は実際に書いた行数。"""
    known = existing_race_codes(path)
    fresh = [r for r in rows if r[0] not in known]
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        if new_file:
            writer.writerow(headers)
        writer.writerows(fresh)
    return len(fresh)
```

2026-07-28 びわこの締切時刻を借りた合成データで動かします。`now` は 13:40 です。

```python:demo.py
from datetime import datetime
from pathlib import Path
from realtime_window import (HoldingRace, JST, SOURCES, append_rows,
                             build_race_code, existing_race_codes,
                             select_eligible_races)

DATE = "2026-07-28"
races = [
    HoldingRace(11, 6, "13:17", ""),       # 締切済み(窓の手前)
    HoldingRace(11, 7, "13:48", ""),       # now+8 分 → 対象
    HoldingRace(11, 8, "14:20", ""),       # now+40 分 → まだ
    HoldingRace(9, 11, "13:45", "途中中止"),  # 中止 → 除外
    HoldingRace(23, 5, "13:41", ""),       # now+1 分 → 境界(含む)
    HoldingRace(23, 4, "確定", ""),         # 締切後の表記 → 除外
]
now = datetime(2026, 7, 28, 13, 40, tzinfo=JST)
root = Path("out")
recorded = {src: existing_race_codes(root / f"{src}.csv") for src in SOURCES}
eligible = select_eligible_races(races, now, DATE, 1, 10, recorded)
print("eligible:", [f"{r.stadium_code:02d}-{r.race_number:02d}@{r.deadline_time}" for r in eligible])

headers = ["レースコード", "レース日", "レース場", "レース回", "締切時刻", "取得日時", "値"]
rows = [[build_race_code(DATE, r.stadium_code, r.race_number), DATE, f"{r.stadium_code:02d}",
         f"{r.race_number:02d}R", r.deadline_time, now.isoformat(), "dummy"] for r in eligible]
print("1 回目 append:", append_rows(root / "stt.csv", headers, rows))
print("2 回目 append:", append_rows(root / "stt.csv", headers, rows))   # 同じ分に再実行 → 0
recorded = {src: existing_race_codes(root / f"{src}.csv") for src in SOURCES}
print("stt だけ記録済みでも再対象:", len(select_eligible_races(races, now, DATE, 1, 10, recorded)))
for src in SOURCES:
    append_rows(root / f"{src}.csv", headers, rows)
recorded = {src: existing_race_codes(root / f"{src}.csv") for src in SOURCES}
print("全ソース記録済み:", len(select_eligible_races(races, now, DATE, 1, 10, recorded)))
```

```text
eligible: ['11-07@13:48', '23-05@13:41']
1 回目 append: 2
2 回目 append: 0
stt だけ記録済みでも再対象: 2
全ソース記録済み: 0
```

同じ `now` で 2 回目を走らせても 0 行、`stt` にだけ書けた状態では次のサイクルでも対象に残り、
4 ソースすべてに揃って初めて対象から外れます。
実装の `select_finished_races()`(結果パス)は、この関数の窓を「締切から `finished_min` 分後以降、上限なし」に変え、
締切の古い順に `catchup_limit` 件で切るだけの違いです。

## 元資料

- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/preview-realtime.py — 1 サイクルの流れ、`select_eligible_races` / `select_finished_races`
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/holding_list.py — 開催一覧 JSON、title CSV フォールバック
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/preview_csv.py — ソースごとのヘッダ、`existing_race_codes` / `append_rows`
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/preview_tsv_scraper.py — `tkz` / `stt` / `sui` のパーサ、CloudFront フォールバックの扱い
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/original_exhibition_scraper.py
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/result_realtime.py、https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/payout_realtime.py — 結果と払戻の独立フェッチャー
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/odds_realtime.py — 集計中オッズ
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/tests/unit/test_select_finished_races.py — 2026-07-28 の回帰テスト
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_index.py — `update_index_for_races` の `状態=realtime` upsert
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md、https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md — CSV の列とスキップルール
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/development.md — Run Realtime Preview Scraper 節(キャッチアップモード)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md — 生成パイプライン節(daily / realtime の状態列)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md — Cloud Scheduler の 2 分毎スケジュールと 300 秒タイムアウト

## 演習

`previews/stt`(スタート展示 ST)と `results/realtime`(本番の実測 ST)を JOIN し、
展示 ST と本番 ST の相関係数を計算してください。
`stt` は艇番基準の列(`艇N_スタート展示`)、`results` はコース基準の列(`Nコース_艇番` / `Nコース_スタートタイミング`)なので、
どちらも `(レースコード, 艇番)` の縦長に直してから結合します。
F は両方とも負値、本番 ST の `-`(欠測)は数値化で落とします。

```python:ex_st_corr.py
import pandas as pd
from urllib.error import HTTPError

BASE = "https://boatracecsv.github.io/data"

def load_month(kind: str, year: int, month: int) -> pd.DataFrame:
    frames = []
    for d in pd.date_range(f"{year}-{month:02d}-01", periods=31):
        if d.month != month:
            break
        try:
            frames.append(pd.read_csv(f"{BASE}/{kind}/{d:%Y/%m/%d}.csv", dtype={"レースコード": str}))
        except HTTPError:      # 開催なし
            pass
    return pd.concat(frames, ignore_index=True)

stt = load_month("previews/stt", 2026, 8)
res = load_month("results/realtime", 2026, 8)

# stt は艇番基準(艇N_スタート展示)、results はコース基準(Nコース_艇番 / Nコース_スタートタイミング)
ex = pd.concat(
    [stt[["レースコード", f"艇{n}_スタート展示"]].rename(columns={f"艇{n}_スタート展示": "展示ST"}).assign(艇番=n)
     for n in range(1, 7)], ignore_index=True)
real = pd.concat(
    [res[["レースコード", f"{c}コース_艇番", f"{c}コース_スタートタイミング"]]
     .rename(columns={f"{c}コース_艇番": "艇番", f"{c}コース_スタートタイミング": "本番ST"})
     for c in range(1, 7)], ignore_index=True)
real["艇番"] = pd.to_numeric(real["艇番"], errors="coerce")
real["本番ST"] = pd.to_numeric(real["本番ST"], errors="coerce")   # "-" (欠測) は NaN
df = ex.merge(real, on=["レースコード", "艇番"]).dropna(subset=["展示ST", "本番ST"])

print("stt レース数:", stt["レースコード"].nunique(), " results レース数:", res["レースコード"].nunique(),
      " JOIN 後の艇数 n =", len(df))
print("相関(全艇):", round(df["展示ST"].corr(df["本番ST"]), 3))
ok = df[(df["展示ST"] > 0) & (df["本番ST"] > 0)]
print("相関(展示 F・本番 F を除く) n =", len(ok), ":", round(ok["展示ST"].corr(ok["本番ST"]), 3))
print("展示 F 率:", round((df["展示ST"] < 0).mean() * 100, 1), "%")
print("平均 展示ST − 本番ST:", round((df["展示ST"] - df["本番ST"]).mean(), 3))
```

2026 年 8 月の 1 か月分で実行した結果です。

```text
stt レース数: 4757  results レース数: 4798  JOIN 後の艇数 n = 27759
相関(全艇): 0.07
相関(展示 F・本番 F を除く) n = 22123 : 0.092
展示 F 率: 18.8 %
平均 展示ST − 本番ST: -0.07
```

相関は **0.070**(n = 27,759 艇走)で、ほとんど無相関です。
第 18 章の ST 推定では、2025-11-01〜2026-07-20 の 234,061 艇走で同じ計算をして **0.047**(展示 F 除外で 0.072)、
バイアス −0.086 秒、展示 F 率 21.7% という値を得ており、月と母数が違っても結論は変わりません。
展示 ST は本番よりおよそ 0.07〜0.09 秒早く、5 艇に 1 艇は展示でフライングしています。
本番と違って展示にはペナルティが無いので、選手は踏み込んで試すのです。
「締切前に取れる貴重な実測値」であっても、そのまま予測値には使えない。
第 18 章はこの数字から始まります。
