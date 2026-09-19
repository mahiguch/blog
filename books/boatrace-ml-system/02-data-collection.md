---
title: "公式データの収集: 1 レース 1 行の CSV"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 学習に使うデータを「事前 / 直前 / 結果」の 3 段階に分けて時間順序を守ること。欠損の意味を自分で決めること(`Nコース_F` の空欄は「正常スタート」、全国平均 ST の `0.00` は「実績なし」であって「最速」ではない) |
| システム | downloader → extractor → parser → converter → storage → git_operations という層構造。レートリミットと指数バックオフ、404 / 403 を再試行しない判断、レースコードで重複を排除する冪等な CSV 追記、共通キーによる JOIN |

第 1 章でボートレースというドメインを整理しました。この章では、そのドメインの出来事を機械学習で扱える形に「記録」する部分、つまりデータ収集を扱います。予想 AI の品質はモデルよりもデータで決まることが多く、boatrace-fun.net でも一番長く手を入れ続けているのがこの層です。

## 1. データソース

### 1.1 2 つの入口

boatracecsv が参照してきた公式系の入口は 2 つあります。

| 入口 | 提供形式 | 現在の扱い |
| --- | --- | --- |
| `www1.mbrace.or.jp/od2/` | 日次の K ファイル(結果)と B ファイル(番組表)。LZH 圧縮された Shift-JIS の固定幅テキスト | 初期のパイプラインの起源。`downloader.py` / `extractor.py` / `parser.py` はこのために書かれた。B ファイルの固定幅パースは脆く(初日に早見が無い行、ボート 2 連率 100.00 でセパレータが消える等)、当日のレース一覧は後述の JSON API に置き換えられ、`parse_program_file` は deprecated になっている |
| `race.boatcast.jp` | レース単位の TSV(`hp_txt/{場}/bc_*_{日付}_{場}_{R}.txt`)と、当日の開催一覧 JSON(`api_txt/getHoldingList2_{YYYYMMDD}.json`) | 現在の一次ソース。出走表詳細・近況・モーター・直前情報・結果・払戻のすべてがここから取れる |

ここで大事なのは、公式サイトが「ファイルで配ってくれるもの」と「画面を描くために裏で読んでいるもの」の両方がデータソースになりうる、という点です。boatcast の TSV は SPA が画面描画のために読み込む静的ファイルで、列の意味は同サイトの JavaScript(`RacerPerformance.js` など)を読んで逆引きしています。`race_card_scraper.py` の冒頭コメントに、39 列の対応表がそのまま残っています。

### 1.2 取れる情報を 3 段階に整理する

収集した CSV は、公開時点によって 3 つのカテゴリに分かれます。これは単なる整理ではなく、学習時に「未来の情報を特徴量に混ぜない」ための境界です。

| 段階 | いつ取れるか | 主なファイル(`data/` 配下) | 内容 |
| --- | --- | --- | --- |
| 事前情報 | 開催日の朝(`daily-sync` が JST 07:30 に起動) | `programs/title`、`programs/race_cards`、`programs/waku10`、`programs/recent_national`、`programs/recent_local`、`programs/motor_stats`、`programs/motor_history`、`programs/monthly_schedule` | 出走表詳細(級別・全国/当地成績・全国平均 ST・F/L 本数・モーター/ボート 2/3 連率・節間 14 スロット成績)、枠番別過去 10 走、全国/当地近況 5 節、モーター期成績と履歴、月間日程 |
| 直前情報 | 各レースの締切 5 分前(`preview-realtime` が JST 08:00〜22:59 に 2 分毎) | `previews/{tkz,stt,sui,original_exhibition,tokuten_hayami}`、`previews/{od1,od2,od3}` | 体重・展示タイム・チルト、進入コースとスタート展示、水面気象、オリジナル展示、得点率早見、集計中オッズ |
| 結果 | 締切 + 3 分以降(同じジョブが終日キャッチアップ) | `results/realtime`、`results/payouts` | 着順・決まり手・実進入コース別 ST・気象、7 舟券種の払戻金と人気 |

この 3 段階に加えて、これらから計算した派生データ(`estimate/` 配下の強さポイント等)がありますが、それは第 4 章以降の話です。

時間軸で見ると、事前情報は前日夜〜当日朝、直前情報は締切 5 分前、結果は締切 3 分後以降に確定します。第 3 章で扱う「締切窓」の判定は、この時刻の並びをそのままコードにしたものです。

![3 段階のデータと取得タイミング](/images/boatrace-ml-system/02-three-stages.png)
<!-- 図: 横軸を 1 日の時刻(07:30 daily-sync 起動、08:00〜22:59 preview-realtime、各レースの締切時刻)にした帯図。事前情報 → 直前情報(締切-5分) → 結果(締切+3分〜)の 3 つの帯を、レースコードが共通キーであることを示す縦線でつなぐ -->

:::message
更新頻度は「1 日 1 回、リアルタイム系は 2 分毎」です。締切直前の最新オッズなど、より鮮度の高い情報が要る場合は別のソース(README で案内している Boatrace OpenAPI 等)を使う設計になっています。boatracecsv が狙っているのは「学習と検証に使える、再現可能な記録」であって、リアルタイム API ではありません。
:::

## 2. 1 レース 1 行という設計

### 2.1 12 桁のレースコードを主キーにする

すべての CSV の先頭列は `レースコード` です。`YYYYMMDDjjrr` の 12 桁で、`jj` は場コード(01〜24)、`rr` はレース番号(01〜12)です。たとえば `202608010101` は 2026 年 8 月 1 日、桐生(01)の 1R を指します。

主キーを 12 桁の文字列 1 本にしたのは、次の理由からです。

- 日付・場・レース番号の 3 列で JOIN するより、1 列で JOIN するほうが pandas でも SQL でも書き間違いが減る
- 文字列のまま辞書順に並べると、そのまま時系列順になる
- 日付が先頭にあるので、ファイルパス `YYYY/MM/DD.csv` と自然に対応する

`dtype=str` で読むことを前提にしています。数値として読むと先頭のゼロは消えませんが(12 桁の先頭は年なので)、場コード `01` を単独で持つ `レース場コード` 列は `1` になってしまい、他ファイルと結合できなくなります。

### 2.2 6 艇分を横に展開する

boatracecsv の CSV は、1 レースの 6 艇分を `艇1_級別, 艇1_全国勝率, ..., 艇6_級別, 艇6_全国勝率` のように横に展開した wide 形式です。2026-08-01 の `race_cards` は 4 列のメタ情報 + 6 艇 × 96 列 = 580 列、`results/realtime` は 50 列、`results/payouts` は 35 列あります。

「1 艇 1 行の long 形式のほうが正規化されていて綺麗ではないか」と思う方も多いはずです。実際、`common.py` には `reshape_programs` / `reshape_previews` / `reshape_results` という wide → long の変換関数があり、特徴量計算では long に戻して使う場面もあります。それでも配布形式を wide にしたのは、次の理由からです。

- 1 レースの予測は「6 艇の相対比較」なので、モデルの入力単位はレースである。行 = レースにしておくと、`pd.read_csv` と `merge(on="レースコード")` だけで学習テーブルが組める
- 結果ファイルの `1着_艇番` と出走表の `艇N_*` を同じ行で参照できるため、「1 着艇の級別」のような特徴量の答え合わせが 1 行で完結する
- long 形式に必要な「艇番」列を全ファイルに持たせるより、列名の接頭辞 `艇N_` に艇番を埋め込むほうが、ファイル間で列名の規約を揃えやすい

### 2.3 パス規約と HTTPS 配信

ファイルは `data/{カテゴリ}/{種別}/YYYY/MM/DD.csv` に置かれ、GitHub Pages から `https://boatracecsv.github.io/` をルートとしてそのまま配信されます。日付ごとにファイルを分けているのは、1 日単位の追記・再生成を git のコミット単位に一致させるためです(第 5 節)。月をまたぐ集計は、読む側が日付範囲のファイルを連結します。

実際に JOIN してみます。以下は 2026-08-01 の出走表詳細と準リアルタイム結果を結合し、1 着艇の級別を数えるコードです。

```python:join_example.py
import pandas as pd

BASE = "https://boatracecsv.github.io/data"
day = "2026/08/01"
cards = pd.read_csv(f"{BASE}/programs/race_cards/{day}.csv", dtype=str)
results = pd.read_csv(f"{BASE}/results/realtime/{day}.csv", dtype=str)

df = cards.merge(results, on="レースコード")
print(cards.shape, results.shape, df.shape)

# 1 着艇の級別を、艇番をキーに横持ちの列から引く
first = df["1着_艇番"].astype(int)
df["1着_級別"] = [df.at[i, f"艇{b}_級別"] for i, b in first.items()]
print(df["1着_級別"].value_counts())
```

実行結果(2026-08-01、n = 156 レース)は次のとおりです。

```
(156, 580) (156, 50) (156, 629)
1着_級別
A1    67
A2    48
B1    35
B2     6
```

出走表 156 行と結果 156 行が 1 対 1 で結合でき、列数は 580 + 50 − 1(共通キー)= 629 になります。`race_cards` と `results/realtime` では場コードの列名が違う(`レース場コード` と `レース場`)のでそのまま並存しますが、レースコードが一致していれば問題ありません。

## 3. スクレイパーの層構造

`scripts/boatrace/` パッケージは、取得から公開までを次の 6 層に分けています。名前は `docs/development.md` の Project Structure にそのまま載っています。

| 層 | モジュール | 責務 | 入力 → 出力 |
| --- | --- | --- | --- |
| downloader | `downloader.py` | HTTP で取る。レートリミットとリトライだけを知っている | URL → `bytes` とステータスコード |
| extractor | `extractor.py` | LZH を展開し Shift-JIS をデコードする | `bytes` → `{ファイル名: テキスト}` |
| parser | `parser.py`、`*_scraper.py` | テキストをドメインのオブジェクト(`RaceCard` 等)にする | テキスト → dataclass のリスト |
| converter | `converter.py` | dataclass を CSV の行に並べ、レースコードを組み立てる | dataclass → CSV 文字列 |
| storage | `storage.py`、`preview_csv.py` | ファイルに書く。既存ファイルの扱い(上書き / 追記 / 重複排除)を決める | CSV 文字列 → ファイル |
| git_operations | `git_operations.py` | `git add` / `commit` / `rebase` / `push` | ファイルパス → 公開 |

![スクレイパーの層構造](/images/boatrace-ml-system/02-scraper-layers.png)
<!-- 図: 左から右へ downloader → extractor → parser → converter → storage → git_operations の 6 箱。各箱の下に入出力(bytes / text / dataclass / CSV str / file / commit)。extractor は mbrace の LZH 経路にだけ使われ、boatcast 経路では downloader から parser(*_scraper.py)へ直接つながることを点線で示す -->

分けた理由は、それぞれの層で「変わる理由」が違うからです。

- 公式サイトの HTML や TSV の列順が変わる → parser だけ直す
- CSV に列を足す → converter と docs だけ直す
- Cloud Run に移して git の認証方法が変わる → git_operations だけ直す
- サーバーが 5xx を返しやすくなった → downloader のリトライ設定だけ直す

実際にこの分割が効いた例が、mbrace の B ファイルから boatcast の TSV への移行です。extractor と固定幅 parser を deprecated にし、`race_card_scraper.py` などの TSV 用 parser と、converter に `race_cards_to_csv` などの出力関数を足しましたが、storage の `write_csv` と git_operations の `commit_and_push` は `race-card.py` からそのまま呼ばれています。第 3 章のリアルタイム収集も、この層構造の上に `preview_csv.py` / `result_realtime.py` という storage 層のモジュールを足す形で作られています。

エントリポイントの `scripts/race-card.py` を読むと、層の使い方が見えます。

1. `holding_list.fetch_holding_list(date)` で当日の開催一覧 JSON を取り、`(場コード, レース番号)` の集合を作る(中止・順延は除外)
2. `RaceCardScraper.scrape_race()` を場 → レース番号の順に呼ぶ(downloader + parser)
3. `race_cards_to_csv()` で CSV 文字列にする(converter)
4. `write_csv()` で `data/programs/race_cards/YYYY/MM/DD.csv` に書く(storage。既存ファイルは `--force` がなければスキップ)
5. 書いたパスがあれば `git_operations.commit_and_push()` する

各層は例外を投げずにログを残して `None` を返す設計に統一されています。1 レースの取得失敗で 1 日分の処理を止めない代わりに、失敗件数を `stats` に集計して最後に表示します。この「静かに失敗するが、必ず数える」方針は第 12 章で改めて扱います。

## 4. 礼儀正しく取得する

### 4.1 取得間隔と負荷について

スクレイパーは相手のサーバーの資源を借りています。boatracecsv では次のことを守っています。

- リクエストは直列に、間隔を空けて出す。並列化はしない
- 取る前に「今、取る必要があるか」を判定する。開催一覧 JSON で中止レースを除き、締切窓に入ったレースだけを対象にし、すでに CSV にあるレースコードは取りに行かない(第 5 節)
- 同じ内容を二度取らない。たとえば水面気象 `bc_sui` は同じ場・同じ時刻なら全レース共通なので、1 回の実行内で場ごとにキャッシュする(`preview-realtime.py` の `sui_cache`)
- 存在しないファイル(404 / 403)は再試行しない。boatcast は存在しないレースに対して 403 と SPA の HTML を返すので、本文が `data=` で始まるかどうかで有効性を判定し、そうでなければ即座に諦める

`RateLimiter` クラスの既定値は 3 秒で、`docs/operations.md` の設定例もこの値です。これは 1 日 2 ファイルを取る mbrace 時代に決めた値です。一方、boatcast からは 1 レースごとに小さな TSV を数百ファイル取る必要があり、リアルタイムジョブは 2 分毎・300 秒のタイムアウトで動くため、リポジトリの `.boatrace/config.json` では `rate_limit_interval_seconds` を 0.1 に下げています。間隔をどこまで詰めてよいかは相手のサーバーが決めることなので、利用規約とサーバーの応答を見ながら、必要最小限の回数で、短時間に集中させずに取る、という原則を守ってください。

### 4.2 RateLimiter と ExponentialBackoff

`downloader.py` の本質は 60 行程度に収まります。実装から構造化ログを除いたものが次のコードです。

```python:polite_download.py
import time
from typing import Optional, Tuple
import requests


class RateLimiter:
    """リクエスト間隔の下限を守る(既定 3 秒)。"""

    def __init__(self, interval_seconds: float = 3.0):
        self.interval_seconds = interval_seconds
        self.last_request_time = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.interval_seconds:
            time.sleep(self.interval_seconds - elapsed)
        self.last_request_time = time.time()


class ExponentialBackoff:
    """失敗するたびに待ち時間を 2 倍にし、上限で頭打ちにする。"""

    def __init__(self, initial_seconds: float = 5.0, max_seconds: float = 30.0):
        self.initial_seconds = initial_seconds
        self.max_seconds = max_seconds
        self.current_attempt = 0

    def get_wait_time(self) -> float:
        return min(self.initial_seconds * (2 ** self.current_attempt), self.max_seconds)

    def increment(self) -> None:
        self.current_attempt += 1


def download_file(
    url: str,
    max_retries: int = 3,
    timeout_seconds: int = 30,
    rate_limiter: Optional[RateLimiter] = None,
) -> Tuple[Optional[bytes], int]:
    """(本文, ステータス) を返す。404 / 403 は即座に諦め、5xx と通信エラーだけ再試行する。"""
    rate_limiter = rate_limiter or RateLimiter()
    backoff = ExponentialBackoff()
    last_status = 0
    for attempt in range(max_retries + 1):
        rate_limiter.wait()
        try:
            response = requests.get(url, timeout=timeout_seconds)
        except (requests.Timeout, requests.ConnectionError):
            last_status = 0          # 通信エラーは再試行対象
        else:
            last_status = response.status_code
            if last_status == 200:
                return response.content, 200
            if last_status in (404, 403):
                return None, last_status   # 「無い」ものは何度取りに行っても無い
        if attempt < max_retries:
            time.sleep(backoff.get_wait_time())
            backoff.increment()
    return None, last_status
```

設計上のポイントは 3 つです。

**RateLimiter は「前回からの経過時間」で待つ。** 毎回固定で `sleep(3)` するのではなく、前回のリクエスト時刻を覚えておき、足りない分だけ待ちます。パース処理に 1 秒かかれば待ちは 2 秒で済み、全体の実行時間が縮みます。1 つの `RateLimiter` インスタンスをスクレイパー全体で共有するのが前提で、`race-card.py` は 1 個作って `RaceCardScraper` と `MonthlyScheduleScraper` の両方に渡しています。

**ExponentialBackoff は 5 → 10 → 20 → 30(上限)秒。** 5xx や通信エラーは「サーバーが一時的に苦しい」状態なので、待ち時間を倍々に伸ばして負荷を下げます。上限を設けるのは、Cloud Run Jobs のタイムアウト(300 秒)の中で必ず終わらせるためです。`max_retries=3` なら最悪でも 5 + 10 + 20 = 35 秒の待ちで諦めます。

**404 / 403 は再試行しない。** これは「取れなかった」ではなく「存在しない」という情報です。開催のない日の K ファイル、まだ公開されていない結果 TSV、中止になったレースは、何度取りに行っても現れません。再試行すると相手に無駄な負荷をかけるだけでなく、自分の実行時間も浪費します。「無い」ことは呼び出し側にステータスコードで伝え、呼び出し側が「次回の実行で再試行する」(第 3 章のキャッチアップモード)かどうかを決めます。

この簡略版を、`requests.get` を差し替えたテストで動かした結果は次のとおりです(`time.sleep` は記録するだけの関数に置き換えています)。

```
200            -> ((b'ok', 200), 1, [])
404 (no retry) -> ((None, 404), 1, [])
403 (no retry) -> ((None, 403), 1, [])
503,503,200    -> ((b'ok', 200), 3, [5.0, 10.0])
503 x4 (give up)-> ((None, 503), 4, [5.0, 10.0, 20.0])
timeout,200    -> ((b'ok', 200), 2, [5.0])
```

3 つ組は(戻り値、HTTP 呼び出し回数、待った秒数のリスト)です。404 と 403 は 1 回で返り、503 は 4 回目で諦め、待ち時間は 5, 10, 20 と伸びていることが確認できます。

## 5. 冪等な追記

### 5.1 「再実行が常に安全」を目標にする

日次バッチもリアルタイムジョブも、必ず途中で落ちます。GitHub Actions の cron は数分遅れることがあり、Cloud Run Jobs はタイムアウトし、boatcast はときどき 5xx を返します。そのとき運用者がやりたいのは「もう一度実行する」ことだけで、「前回どこまで書いたか確認してから実行する」は避けたい作業です。

そのために、boatracecsv の追記系ファイル(`previews/*`、`results/*`)は次の規約を守っています。

- 同一 `レースコード` は 1 日のファイルに 1 行だけ
- 追記の前に、そのファイルにすでにあるレースコードの集合を読み、含まれる行は捨てる
- 追記した行が 0 なら、ファイルにも git にも触らない

3 つ目が重要です。`preview-realtime.py` は 2 分毎に動きますが、対象レースがなければ何もコミットしません。コミットの有無が「新しい行があったか」と一致するので、git の履歴がそのまま取得ログになります。

### 5.2 簡略版コード

`preview_csv.py` と `result_realtime.py` にある `existing_race_codes` / `append_rows` を、dedup まで含めて 1 関数にまとめると次のようになります。実装では dedup を呼び出し側の責務にしていますが(ソースごとに「どのレースをまだ取っていないか」の判定を先にしたいため)、本質は同じです。

```python:append_dedup.py
import csv
from io import StringIO
from pathlib import Path
from typing import Iterable, List, Set


def existing_race_codes(path: Path) -> Set[str]:
    """すでに CSV にあるレースコード(先頭列)の集合。ファイルが無ければ空集合。"""
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # ヘッダを読み飛ばす
        return {row[0] for row in reader if row}


def append_rows(path: Path, headers: List[str], rows: Iterable[List[str]]) -> int:
    """レースコードが未記録の行だけを追記し、書いた行数を返す。何度呼んでも結果は同じ。"""
    seen = existing_race_codes(path)
    new_rows = [r for r in rows if r[0] not in seen]
    if not new_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    buf = StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    if new_file:
        writer.writerow(headers)
    writer.writerows(new_rows)
    with open(path, "a", encoding="utf-8") as f:
        f.write(buf.getvalue())
    return len(new_rows)
```

同じ 2 行を 2 回、次に 1 行重なった 2 行を追記するテストの出力です。

```
1st run: 2
2nd run (same): 0
3rd run (overlap): 1
codes: ['202608010101', '202608010102', '202608010103']
line count: 4
```

2 回目は 0 行(= コミットしない)、3 回目は重複を除いた 1 行だけが書かれ、ファイルはヘッダ + 3 行になります。

細かい点をいくつか補足します。

- 行をいったん `StringIO` に組み立ててから 1 回の `write` で追記しているのは、途中で例外が起きたときに半端な行を残さないためです
- 戻り値は「実際に書いた行数」です。呼び出し側はこれを合計し、0 なら `commit_and_push` を呼びません(`preview-realtime.py` の `if not (args.dry_run or args.no_commit or not paths)`)
- `git_operations.commit()` 側でも `nothing to commit` を成功扱いにしているので、二重に守られています
- 日次で再生成する `programs/*` は追記ではなく「ファイル単位の上書き」で、`write_csv` は既存ファイルがあると `--force` なしではスキップします。追記型と上書き型で冪等性の担保のしかたが違う点は、第 3 章で `upsert` が出てきたときにもう一度確認します

:::message
dedup の単位を「レースコード」にしているため、同じレースの値が時間とともに変わるデータ(オッズ、気象)は最初の 1 回しか記録されません。boatracecsv では直前情報を「締切 5 分前のスナップショット 1 枚」と定義することでこの制約を受け入れています。時系列で追いたいなら、キーに取得時刻を含める別の設計が必要です。
:::

## 6. 欠損の意味を決める

CSV の空欄や `0` には、ソースごとに違う意味があります。この意味を決めずに数値として下流に流すと、モデルは間違った学習をします。boatracecsv で実際に起きた 2 つの例を挙げます。

### 6.1 `Nコース_F` はドキュメントの 1/0 ではなく文字 `F` / 空欄だった

`results/realtime` には、実際の進入コース順に `Nコース_艇番` / `Nコース_スタートタイミング` / `Nコース_F` の 3 列 × 6 コースがあります。`docs/data/results.md` の旧記述と、それを引いた `docs/design/st_estimation.md` の初版(2026-07-20)では、この `Nコース_F` を「1 = フライング / 0 = 正常」と書いていました。ところが、ST 推定のために実測 ST のパネルを組んだ Phase 1(`notebooks/st_estimation/report.md`)で実データを確認すると、値は `1` / `0` ではなく文字 `"F"` / 空欄でした。`result_realtime.py` の `build_result_row` を読むと、確かに `"F" if c.is_flying else ""` と書いてあります。

このずれ自体は `pd.to_numeric` で全部 NaN になって気づけるたぐいのものですが、パネル構築で同時に確定した次の事実のほうが重要です(2025-11-01〜2026-07-20、39,081 レース、234,061 艇走)。

- F 艇の `Nコース_スタートタイミング` は負値で記録される(853 件、範囲 −0.14〜−0.01)
- F マークが無いのに ST が負値の行が 7 件ある(データ側の癖)。したがって「F」の判定は `F` マークと `ST < 0` の OR にする
- L(出遅れ)には専用マークが無く、大きな ST(0.5 超が 243 件、最大 0.99)として数値のまま記録される。実際に起きたスタートなので正解データには含める
- 実測 ST の欠損は `-` の 5 件のみ。ただし `race_cards` と結合できない艇走が 4,849 件(2.1%)、`stt`(スタート展示)が無いレースが 8.0% ある

つまり、「フライングか」を知りたいなら `F` 列の空欄を「正常」と読み、念のため ST の符号も見る。「出遅れか」を知りたいなら ST の大きさで判断する。この規則は `docs/data/results.md` に書き戻され、設計書 §2.1 の「未決」が「確定」に変わりました。ドキュメントが実データとずれるのはよくあることで、ずれを見つけたらコードではなくドキュメントの側を直す、という運用にしています。

なお公開 CSV でも確認できます。2026-08-01〜07 の 7 日分(971 レース、5,826 艇走)では `F` マークが 15 件、負値の ST も 15 件で、この週はきれいに一致していました。

### 6.2 全国平均 ST `0.00` は「実績なし」であって「最速」ではない

`race_cards` の `艇N_全国平均ST` は、期(約 6 ヶ月)の平均スタートタイミングです。デビュー直後で集計対象の出走が無い選手はここが `0.00` になります(CSV 上は浮動小数の書式で `0.0` と出ることがあるので、文字列ではなく数値で比較してください)。2026-08-01 の 156 レースでは 936 艇のうち 15 艇、8 月 1〜7 日の 7 日分では 5,826 艇走のうち 70 艇走がこれに該当しました。

問題は、この `0.00` が「速い」方向の値であることです。boatrace-fun.net のスリット展開図は、1 マークまでの走行距離を

```
distance = (1 − 全国平均ST) + 強さpt / 50 − 1.6
```

で計算します(第 15 章)。ST が小さいほど距離が伸びる式なので、`0.00` をそのまま入れると「実績のない新人が全艇で最速スタートを切る」絵になります。描画側は `NO_RECORD_ST_FOR_DRAW` で 0.25 に置き換えていたのに、距離計算側は生の `0.00` を使っていて、`docs/design/st_estimation.md` §1.2 に「欠損処理が ad hoc」「距離計算では最速扱い」と課題として書かれました。

修正は 2026-07-20 に fun-site 側で行われ、`packages/shared/src/utils/one-mark-distance.ts` に `NO_RECORD_ST_FALLBACK = 0.25` と `effectiveAvgST()` を置いて、描画と距離計算の両方で `0.00` → 0.25 に統一しました。効果は Phase 1 のベースライン比較で測られていて、補完なし(B0raw)と補完あり(B0)で MAE 0.0581 → 0.0548(−0.0033)、スリット順位の Spearman ρ 0.202 → 0.226、隊形 3 分類一致率 +1.9pt でした(2025-11-01〜2026-07-20、234,061 艇走)。

さらに、パネルで「公表 ST = 0.00 の艇」の実測 ST を集計すると平均 0.197(4,067 艇走)でした。0.25 という補完値は方向としては正しいものの、やや遅すぎます。級別の実測平均が A1 0.146 / A2 0.161 / B1 0.172 / B2 0.187 と綺麗に並ぶので、「級別の平均で補完する」(H6)が次の候補として設計書に残っています。第 18 章の ST 推定は、この欠損補完を含めた ST の推定そのものをテーマにしています。

### 6.3 空欄の意味はファイルごとに違う

上の 2 例のほかにも、`docs/data/*.md` には空欄の意味が個別に書いてあります。抜粋すると次のとおりです。

| ファイル | 列 | 空欄 / 0 の意味 |
| --- | --- | --- |
| `race_cards` | `艇N_F本数` / `艇N_L本数` | 空欄は 0 本 |
| `race_cards` | `艇N_早見` | 当日 2 レース出場でなければ空欄 |
| `race_cards` | `艇N_節D{D}走{S}_*` | 未出走スロットは全列空欄(節が進むほど埋まる) |
| `waku10` | `艇N_過去{n}走_進入` | 空欄は「枠なり進入」(枠と違うときだけ値を持つ) |
| `motor_stats` | `平均ラップ秒` 等 3 列 | 連対実績ゼロのモーターは boatcast 側で算出されないため空欄(直近サンプルで 3.0%) |
| `previews/stt` | `スタート展示` | F は負値、L は空欄 |
| `results/payouts` | 拡連複 9 列 | 5 艇立て以下では販売がないため全列空欄 |

`common.py` の `prepare_features` では、着順系の列は 3.5(6 艇の中央)、率系の列は中央値で欠損を埋めています。しかしこれは「意味を決めた後」の話です。空欄 = 0 なのか、空欄 = 該当なしなのか、空欄 = 取得失敗なのかは、上の表のようにソースごとに決めてドキュメントに書き、下流はそれを読んで補完方法を選びます。第 4 章の偏差値化では、まだ取得していない展示・気象は 50(平均 = 中立)で、近 5 節の出走履歴が無い選手の選手ptは平均扱いだと過大評価になるので 30 で補完する、という使い分けが出てきます。同じ「空欄」でも、それが「まだ来ていない」のか「実績が無い」のかを先に決めているからできる使い分けです。

## 元資料

- boatracecsv [`README.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/README.md)
- boatracecsv [`docs/data/README.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/README.md) — ファイル一覧と関係性図
- boatracecsv [`docs/data/programs.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md)、[`docs/data/previews.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md)、[`docs/data/results.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md)
- boatracecsv [`docs/development.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/development.md)、[`docs/operations.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/operations.md)
- boatracecsv [`scripts/boatrace/downloader.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/downloader.py)、[`extractor.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/extractor.py)、[`parser.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/parser.py)、[`converter.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/converter.py)、[`storage.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/storage.py)、[`git_operations.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/git_operations.py)、[`common.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/common.py)
- boatracecsv [`scripts/boatrace/holding_list.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/holding_list.py)、[`race_card_scraper.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/race_card_scraper.py)、[`result_realtime.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/result_realtime.py)、[`preview_csv.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/preview_csv.py)
- boatracecsv [`scripts/race-card.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/race-card.py)、[`scripts/preview-realtime.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/preview-realtime.py)
- boatracecsv [`docs/design/st_estimation.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/st_estimation.md)、[`notebooks/st_estimation/report.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/notebooks/st_estimation/report.md) — `Nコース_F` の実態と平均 ST 0.00 の扱い
- fun-site [`packages/shared/src/utils/one-mark-distance.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/utils/one-mark-distance.ts) — `NO_RECORD_ST_FALLBACK`

## 演習

1. 任意の 1 週間分の `programs/race_cards` と `results/realtime` をレースコードで JOIN し、級別(A1 / A2 / B1 / B2)ごとの 1 着率を出してください。wide 形式のままだと集計しにくいので、`艇1_級別`〜`艇6_級別` を艇番つきの long 形式に変換し、`1着_艇番` と一致するかどうかの列を作ってから `groupby("級別")` するのが近道です。2026-08-01〜07 の 7 日分なら 971 レースが結合できます。
2. 同じ 7 日分で、`Nコース_F == "F"` の件数と `Nコース_スタートタイミング < 0` の件数を数え、両者が一致するか確かめてください。一致しない行があれば、そのレースコードを控えておくと第 18 章の前処理ルールの意味がわかります。
3. `艇N_全国平均ST` が 0 の艇走を抜き出し、その艇の `艇N_級別` と `艇N_全国勝率` を見てください。「実績なし」と「ST が 0.00 秒」のどちらの解釈が自然か、値の分布から説明してください。
