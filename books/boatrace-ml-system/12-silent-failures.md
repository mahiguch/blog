---
title: "沈黙する失敗との戦い"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 学習母数が知らないうちに 31% 減っていた事故。「全履歴で学習」と書いてあるコードの母数を決めていたのは、コードではなくインフラの設定だった。古い係数で推論して静かに壊れることをどう防ぐか |
| システム | エラーにならない失敗の型(書いたのに消える、減っているのに動く、古いまま動く、片方だけ取れる、無いのに 200 が返る)、観測可能な不変条件をログに置く、学習と推論の分離、依存順序を明示して「作り方を示して落ちる」 |

第 11 章で、3 つの Cloud Run Job がそれぞれ別の cone-mode sparse-checkout でリポジトリの一部だけを取り出して動く仕組みを説明しました。
preview-realtime は 1 GiB のメモリ制約の下で動き、Cloud Run の `/tmp` は tmpfs でチェックアウトした分だけメモリを食うので、フル clone を避けるこの設計自体は正しい選択です。
しかし「ジョブごとに見えているファイルが違う」という状態は、エラーにならない失敗を生みます。
書いたはずのファイルが消え、学習に使ったはずのデータが減り、それでもジョブは成功終了します。

この章は、2026 年 8 月に穴予想(第 20〜21 章)を投入した直後の 10 日間に起きた、3 つの「沈黙する失敗」の記録です。
どれもスタックトレースは出ませんでした。気づいたのはログの数字を疑ったときと、コードを読み直したときです。
最後に、これらを 5 つの型に分類し、それぞれに対して「音を出す失敗」に変える方法をまとめます。

![2026-08-11 から 09-01 までの時系列](/images/boatrace-ml-system/silent-failures-timeline.png)
<!-- 図: 横軸を日付にしたタイムライン。08-11 v9_suji 投入、08-12 荒れ度メーター・v10_kimarite・tokuten_hayami 投入、08-13 preview-realtime の git add が丸ごと失敗(同日 20:25 修正)、08-22 v9_suji 退役 → 18:22 静的テーブルの永続化(#8) → 18:54 全履歴で学習(#9)、09-01 06:06 monthly-weights が初めて tables/ を commit(logloss.csv 初出)。失敗が起きた時点と気づいた時点を色分けする -->

## 1. cone の外に書いたファイルは消える

### 1.1 cone-mode sparse-checkout の前提

cone-mode の sparse-checkout は、「このディレクトリ以下だけを作業ツリーに展開する」というリストを持ちます。
monthly-weights ジョブなら `infra/run-monthly-weights.sh` の `paths` 配列、preview-realtime なら `infra/run.sh` の `sparse_paths` 配列がそれです。
リストに無いディレクトリは作業ツリーに存在しません。ただし、スクリプトが `mkdir -p` してそこにファイルを書くことは普通にできます。
問題は、その後の `git add` です。

手元の git 2.50 で、cone の外にあるファイルを `git add` するとどうなるかを試しました。

```bash
$ git sparse-checkout init --cone && git sparse-checkout set data/in
$ echo new > data/out/c.csv            # cone の外
$ echo new > data/in/d.csv             # cone の中
$ git add data/in/d.csv data/out/c.csv ; echo "rc=$?"
The following paths and/or pathspecs matched paths that exist
outside of your sparse-checkout definition, so will not be
updated in the index:
data/out/c.csv
rc=1
$ git status --short
A  data/in/d.csv
?? data/out/c.csv
```

cone の中のファイルはステージされ、外のファイルは警告とともに無視され、終了コードは 1 になります。
ここから 2 つの異なる失敗が派生します。呼び出し側がこの終了コードをどう扱うかで、結果が正反対になるからです。

### 1.2 型 A: 列挙にも漏れていると、何も起きない

monthly-weights は毎月 1 日に `build_suji_table.py` と `build_kimarite*.py` を走らせ、
`data/estimate/{suji,kimarite}/tables/` に静的テーブル(スジ表、決まり手セルの係数、ペア表、校正表、log-loss 表)を書きます。
2026-08-22 のコミット `e817dcfdb0c`(PR #8)のメッセージから引用します。

> それらのパスが cone-mode sparse-checkout の paths 配列にも末尾の git add にも入っておらず、生成物が毎月無言で捨てられていた。実際 git log を見ると tables/ 配下は導入時の feature commit 以降 1 度も更新されておらず、logloss.csv に至ってはリポジトリに存在しない。

`git add` の引数に列挙されていないファイルは、cone の内外に関係なく、そもそも git の目に触れません。
スクリプトは正常終了し、ログにも「wrote data/estimate/kimarite/tables/cell_coef_daily.csv」と出ます。
ジョブが終わってコンテナが消えると、ファイルも一緒に消えます。
これが最も静かな型です。エラーも警告も無く、痕跡は「リポジトリ内のファイルが更新されていない」という不在だけです。

`logloss.csv` は v10_kimarite の**退役判定の主指標**です(第 21 章。`95%CI下限` が 0 を下回ったら退役する)。
`git log --diff-filter=A` で確認すると、このファイルがリポジトリに初めて現れたのは 2026-09-01 06:06 のコミット `925b8e7e2b0`、つまり修正後の初回月次実行です。
v9_suji のテーブルは 2026-08-11、荒れ度メーターのテーブルは 2026-08-12 の feature commit で入って以来、2026-09-01 まで一度も更新されていません。

:::message
この失敗は、本番で「捨てられた」実績が出る前に見つかっています。
テーブルを吐くスクリプトが monthly-weights に入ったのは 2026-08-11〜12 で、次の月次実行は 09-01 でした。
08-22 の修正が無ければ、09-01 の実行で退役判定に必要な `logloss.csv` が作られ、そして捨てられていたはずです。
コミットメッセージにも「2026-09-01 で退役判定ができなくなるところだった」とあります。
見つけたきっかけは、コードを読んで「この出力はどこで commit されるのか」を追ったことでした。
:::

修正は、`paths` 配列と末尾の `git add` の**両方**に `data/estimate/suji/tables` と `data/estimate/kimarite/tables` を足すことです。
現在の `run-monthly-weights.sh` は末尾でこう書いています。

```bash:infra/run-monthly-weights.sh(抜粋)
# 静的テーブルの書き込み先はすべてここに列挙する。cone の外のパスを
# 混ぜると `git add` 全体が失敗する / cone 内でも列挙し忘れると生成物が
# 黙って捨てられる (上の sparse-checkout ブロック参照)。
git add \
  data/estimate/stadium/weights/ \
  data/estimate/stadium/course_win_rate.csv \
  data/estimate/suji/tables/ \
  data/estimate/kimarite/tables/
```

同じコミットで、集計側の**入力**も cone に足しています。
`build_kimarite_logloss.py` は `data/estimate/kimarite/YYYY/MM/` の日次予測 CSV と `data/estimate/v10_kimarite/` の強さポイントを読むので、
これらが無いと `git add` を直しても `logloss.csv` は n=0 の空表になります。
「書き込み先を cone に足す」だけでは半分で、「そのスクリプトが読むものが cone にあるか」まで確認して初めて修正が完了します。

### 1.3 型 B: 列挙されていると、全部が落ちる

反対の失敗は preview-realtime で起きました。
2026-08-12 22:21 のコミットで、得点率早見 `tokuten_hayami` という新しい直前情報の CSV を `data/previews/tokuten_hayami/YYYY/MM/DD.csv` に書くようにしました。
このとき `run.sh` の `sparse_paths` に `data/previews/tokuten_hayami/${TODAY_YM}` を足し忘れました。

preview-realtime は 2 分毎に、その回で書いた全ファイルのパスをリストにして `git_operations.commit_and_push(rel_paths, message)` を 1 回だけ呼びます。
`stage_files()` の中身はこうです。

```python:scripts/boatrace/git_operations.py(抜粋)
def stage_files(files: List[str]) -> bool:
    if not files:
        return True
    try:
        subprocess.run(
            ["git", "add"] + files,
            capture_output=True,
            check=True,          # 非 0 なら CalledProcessError
            cwd=str(project_root),
        )
        return True
    except subprocess.CalledProcessError as e:
        logging_module.error(
            "stage_files_failed",
            files_count=len(files),
            error=e.stderr.decode() if e.stderr else str(e),
        )
        return False
```

`check=True` なので、1.1 で見た終了コード 1 は例外になり、`stage_files()` は `False` を返し、`commit_and_push()` はそこで打ち切ります。
git 自身は cone 内のファイルをステージ済みですが、コミットは作られず、次のサイクルでは新しい clone から始まるので消えます。
結果として、2026-08-13 は展示タイムも進入コースも気象も、その日の直前情報が**一切** commit されませんでした
(`docs/infrastructure.md`「得点率早見 `tokuten_hayami` の追加」の記述。同日 20:25 のコミット `96db9614ab3` で修正)。

こちらは型 A と違って、ログに `event=stage_files_failed` が出て、`preview-realtime.py` も exit code 1 で終わります。
それでも `docs/infrastructure.md` が症状として記録しているのは「サイトの直前情報がまったく更新されない」で、修正が入ったのは翌 08-13 の 20:25 です。
2 分毎に走るジョブの 1 回の失敗は、それ自体では誰にも届きません。「ログには出ている」と「気づける」は別です。

:::message alert
型 A と型 B は同じ原因(cone の外に書いた)から出ますが、症状は正反対です。
型 A は何も失わずに見えて実は新しいものだけを失い、型 B は 1 つのミスで cone 内の正常なファイルまで道連れにします。
`git add` を 1 回にまとめるか、ファイルごとに分けるかで、どちらの型になるかが決まります。
boatracecsv では preview-realtime のコミットを「その回の観測の単位」として扱いたいので 1 回にまとめる設計を維持し、
代わりに `PREVIEW_SOURCES` に種別を足す PR では `run.sh` の `sparse_paths` を同じ PR で更新する、という運用ルールにしました。
:::

### 1.4 パスの切り方にも罠がある

もう 1 つ、cone-mode に固有の落とし穴があります。cone は**ディレクトリ単位で親優先**です。
`data/estimate/suji` を丸ごと cone に入れると、`tables/` だけでなく `2026/08/` のような日次ファイルの全履歴まで展開されてしまいます。
2 分毎のジョブで毎回それを取るのは無駄なので、`data/estimate/suji/tables`(静的)と `data/estimate/suji/${TODAY_YM}`(当月の日次)を**別のエントリとして**指定しています。
v10_kimarite の買い目も同じ理由で `data/estimate/kimarite/picks/${TODAY_YM}` を `data/estimate/kimarite/${TODAY_YM}` とは別に足しています。
出力先のディレクトリ設計そのものに「sparse-checkout で切りやすいか」という観点が入る、というのは、ローカルで開発している間は思いつきにくい制約です。

## 2. 学習母数が cone の広さで決まっていた

### 2.1 「全履歴で学習」の実態

型 A の修正(PR #8)の 30 分後、同じ日の 18:54 に 2 つ目の修正 `afb9a8df901`(PR #9)が入っています。
PR #8 のコミットメッセージは「既知の制限として残したもの」という段落で終わっていました。

> build_kimarite.py だけは race_cards / previews/{tkz,sui} も日ごとに引くが、これらは月単位ループぶん (8 ヶ月) しか cone に入っていないため、docstring の「全履歴で学習」に反して母数が直近 8 ヶ月になる。

`build_kimarite.py` は荒れ度メーター(第 20 章)の Stage1、決まり手セルの多項ロジスティック回帰を学習するスクリプトです。
docstring には「学習窓 = 全履歴」と明記されています。データ収集のループはこうなっています。

```python:scripts/build_kimarite.py(抜粋)
for res_path in sorted(
    (repo / "data" / "results" / "realtime").glob("*/*/*.csv")
):
    rel = res_path.relative_to(repo / "data" / "results" / "realtime")
    cards = read_by_race(repo / "data" / "programs" / "race_cards" / rel)
    if not cards:
        continue
    stt = read_by_race(repo / "data" / "previews" / "stt" / rel)
    tkz = read_by_race(repo / "data" / "previews" / "tkz" / rel)
    sui = read_by_race(repo / "data" / "previews" / "sui" / rel)
    ...
```

`data/results/realtime/` の全日をループし、同じ日付の `race_cards`(出走表)を読み、**無ければ `continue`** します。
`read_by_race` はファイルが無いとき空 dict を返すので、例外は出ません。
ローカルの完全な clone では、結果があって出走表が無い日は存在しないので、この `continue` は「念のため」の分岐に見えます。

ところが monthly-weights の cone では事情が違います。
このジョブの主目的は `build_weights.py`(第 7 章の強さポイントの重み)で、そちらは直近 6 か月しか使いません。
そのため `race_cards` や `previews/{tkz,sui}` は「対象月 + 6 か月 + motor_stats の fallback 用 1 か月 = 8 か月」ぶんだけ月単位で cone に入れていました。
`data/results/realtime/` だけは別の全履歴スクリプト(`build_course_rate.py` など)のために全期間 cone に入っています。
つまり `build_kimarite.py` から見ると、「結果はあるが出走表が無い日」が 8 か月より前に大量にあり、それが全部 `continue` で飛ばされていました。

### 2.2 数字で見る

PR #9 のコミットメッセージには、2026-09-01 の実行を想定した cone を実際に clone して再現した数字があります。

| 条件 | 学習母数 | 出典 |
| --- | --- | --- |
| 8 か月窓の cone(修正前) | 30,160 レース | `afb9a8df901` コミットメッセージ |
| 全履歴(修正後) | 43,595 レース | 同上、`docs/infrastructure.md` |
| 欠落 | 13,435 レース = **31%** | 同上 |

さらに悪いことに、この欠落幅は固定ではありません。
`data/results/realtime/` は 2025 年 11 月から始まっており、8 か月窓は毎月 1 か月ずつ後ろへずれます。
9 月に 31% だった欠落は、翌月には 8/11、翌々月には 8/12 と、履歴が伸びるほど「全履歴」からの乖離が広がります。
月次で再学習するたびに母数が実質固定されたまま、データだけが増えていく状態でした。

学習結果への影響も同じコミットメッセージにあります。
train を 2026-07-01 以前、test をそれ以降に固定した同一ホールドアウトで、全履歴 vs 8 か月窓の log-loss は
realtime で 1.8501 vs 1.8556 nat、daily で 1.8948 vs 1.8971 nat でした。
差は小さいですが、「学習データを増やしたのに母数が増えていない」という状態は、第 20 章の「one-hot の判定が 7,000 レースでは効かず 31,000 レースで効いた」ような、母数に依存する判断をすべて狂わせます。

![8 か月窓の cone と全履歴の結果ファイル](/images/boatrace-ml-system/silent-failures-cone-window.png)
<!-- 図: 横軸を 2025/05 から 2026/09 までの月にした帯グラフ。上段 data/results/realtime は 2025/11 から全月が塗られている。中段 data/programs/race_cards は 2025/05 から存在するが、修正前の cone では 2026/01〜2026/08 の 8 か月だけが塗られ、それ以外は点線。下段に build_kimarite.py のループ矢印を描き、race_cards が無い月には「continue」のラベルを付ける。修正後は 2 段階目の sparse-checkout add で 2025/11 以降が塗られる -->

### 2.3 なぜ race_cards だけ 2 段階にしたか

修正は「3 ファミリ(`race_cards`、`previews/tkz`、`previews/sui`)とも全履歴を cone に入れる」ですが、入れ方が 2 通りに分かれています。

`previews/{stt,tkz,sui}` は `results/realtime` と同じ 2025/11 開始なので、ディレクトリごと cone に入れても取得量は必要な月ぶんと変わりません(tkz 約 7MB、sui 約 4MB)。
一方 `race_cards` は 2025/05 開始で、2025/05〜10 の約 42MB は `results/realtime` より前、つまり `build_kimarite.py` から 1 日も参照されない死荷重です。
tmpfs の制約があるので、`race_cards` だけは `git checkout` の後に `data/results/realtime/` の実ディレクトリから月を列挙し、`git sparse-checkout add` で追加します。

```bash:infra/run-monthly-weights.sh(抜粋)
history_months=()
while IFS= read -r ym; do
  history_months+=("${ym}")
done < <(cd data/results/realtime && ls -d [0-9][0-9][0-9][0-9]/[0-9][0-9] 2>/dev/null | sort)

history_paths=()
for ym in "${history_months[@]}"; do
  history_paths+=("data/programs/race_cards/${ym}")
done
git sparse-checkout add "${history_paths[@]}"
```

月リストの出所を `build_kimarite.py` のループ元と同じ `data/results/realtime/` にしているのが要点です。
「2025-11 開始」という epoch を定数で持たないので、履歴が伸びても過去が backfill されても、学習に使う日とチェックアウトする日が自動的に一致します。

cone の大きさは、修正前が約 304MB、修正後が約 321MB(+9MB/月)、`race_cards` を丸ごと入れた場合が約 374MB です(2026-08 実測、`docs/infrastructure.md`)。
`build_kimarite.py` の peak RSS は全履歴 43,595 レースで 578MB、約 9.6KB/レースで伸びるので、2Gi のジョブが上限に近づくのは約 2 年後と見積もられています。

### 2.4 不変条件をログに置く

この失敗の本質は、「学習母数は何で決まるか」という問いの答えが、スクリプトの中ではなくシェルスクリプトの配列にあったことです。
コードレビューで `build_kimarite.py` だけを読んでも見つかりません。
再発を防ぐために、修正後は**観測可能な不変条件**を 1 つ決めました。

`build_kimarite.py` は学習前に次の形式の 1 行を出力します。

```
races=NNNNN (YYYY-MM-DD 〜 YYYY-MM-DD) classes=NN
```

この左端の日付が `data/results/realtime/` の最古日と一致していれば、cone は欠けていません。
PR #9 の検証では、修正後の cone で `races=43598 (2025-11-01 〜 ...)` となり、フル checkout と一致したことが確認されています。
ズレていれば、どこかの月の `race_cards` が cone に無く、その分が `continue` で飛んでいます。
`run-monthly-weights.sh` はこの検証手順をコメントとして `build_kimarite.py` の呼び出し箇所に置き、`docs/operations.md` にも「再発検知」として書いてあります。

「母数と範囲をログに出す」だけなら 1 行です。
しかし、その値が**何と一致していなければならないか**(ここでは `results/realtime` の最古日)まで決めておかないと、ログは数字が流れるだけで検知にはなりません。
不変条件とは、「壊れていなければ必ず成り立つ、外から確認できる等式」のことです。

## 3. 学習と推論を分ける

### 3.1 推論は係数 CSV から softmax を直接計算する

`build_kimarite.py` は sklearn で学習しますが、出力するのはモデルのバイナリではなく係数 CSV です。

```
行種別,クラス,切片,w1_級別,w1_F本数,w1_全国勝率,...
median,,,3,0,5.71,...
center,,,2.88723,0.0970716,5.58541,...
scale,,,0.891346,0.301865,1.1093,...
coef,その他_1,-0.96407,0.0106989,-0.0179467,...
coef,その他_2,-1.73591,-0.0315771,-0.0142946,...
...(32 クラス)
```

1 行が 1 クラスの係数で、先頭 3 行に欠損補完用の中央値と標準化パラメータを持ちます。
推論側の `build_kimarite_probs.py` は sklearn を import せず、この CSV から標準化 → 線形結合 → softmax を純 Python で計算します。

なぜ分けるのか。理由は 2 つあります。
1 つは、推論が 2 分毎の preview-realtime と毎朝の daily-sync で走ることです。
毎回 sklearn とモデルファイルを読み込むより、36 行の CSV を読むほうが軽く、依存も小さくて済みます。
もう 1 つは、この章の主題である「古いまま動く」を防げることです。
モデルバイナリは中身が見えませんが、係数 CSV は「どのクラスの係数が入っているか」をヘッダ名で検査できます。

### 3.2 係数のクラス構成が CELLS とズレていたら落とす

決まり手セルのクラス一覧は `boatrace.kimarite.CELLS` にコードとして**凍結**されています(2026-08-12 時点の全履歴で n ≥ 60 だった 26 セル + 受け皿の「その他_{1着コース}」6 個 = 32 クラス)。
月次再学習のたびに閾値を評価し直すとクラスが増減して CSV のスキーマが変わるので、データが増えて新しいセルが 60 を超えても、コードを手で更新するまでは「その他」に入ります。

推論側は係数 CSV を読んだ直後にこの一覧と突き合わせます。

```python:scripts/build_kimarite_probs.py(抜粋)
if tuple(classes) != CELLS:
    raise ValueError(
        f"{path}: クラス構成が boatrace.kimarite.CELLS と一致しません。\n"
        f"  係数 CSV が古い可能性があります。build_kimarite.py を再実行してください"
    )
```

順序まで含めた完全一致を要求します。
もし CELLS を更新したのに月次学習が(1 節の型 A のように)新しい係数を永続化できていなければ、推論は古い 32 クラスの係数で新しい特徴量を読むことになります。
softmax は何を入れても確率の形をした数字を返すので、落とさなければサイトには「それらしい荒れ度」が出続けます。
黙って動くより、黙って動かないほうが安全です。

同じ思想は Stage2 のペア表にもあります。`kimarite_blend.load_pair_table()` は、`CELLS` のうちペア表に無いセルがあれば
「ペア表が古い可能性があります。build_kimarite_pairs.py を再実行してください」という `ValueError` を投げます。
逆に、日次の確率 CSV を読む `read_cell_probs()` は列を `P_{セル}` というヘッダ名で引くので、CELLS の並びが変わっても壊れません。
「どこで厳しく、どこで寛容にするか」を、ファイルの役割(学習の出力か、集計の入力か)で決めています。

## 4. 依存順序を壊さない

### 4.1 順序を崩すと買い目が 0 行になる

v10_kimarite の買い目は、3 つのスクリプトの出力を順に組み合わせて作られます。

```
build_index.py --predictor v10_kimarite   … 強さポイント(第 7 章)
build_kimarite_probs.py                   … Stage1 の 32 クラス確率
        ↓
build_kimarite_picks.py                   … 合成 → ブレンド → 上位 5 点
```

`build_kimarite_picks.py` は index の行ごとに Stage1 の確率を引き、**確率が無いレースは無言でスキップ**します。

```python:scripts/build_kimarite_picks.py(抜粋)
p1 = cell_probs.get(code)
if p1 is None:
    # Stage1 の確率が無いレースは買い目を出さない
    # (build_kimarite_probs.py が先に回っている必要がある)
    continue
```

これは意図した挙動です。直前バッチでは締切が近いレースだけ確率が更新されるので、「確率が無い = まだ対象外」であって異常ではありません。
しかし daily-sync で `build_kimarite_probs.py` より先に `build_kimarite_picks.py` を走らせてしまうと、全レースがこの `continue` に当たり、買い目 CSV は 0 行で正常終了します。
`docs/operations.md` に「これを崩すと買い目が 0 行になる」と書いてあるのはこのためで、`run-daily-sync.sh` の該当ステップには
「`build_index.py` と `build_kimarite_probs.py` の**両方**の後に走らせる」というコメントが付いています。

### 4.2 前提ファイルが無いときは「作り方を示して落ちる」

一方で、前提ファイルそのものが無い場合は落とします。
それも素の `FileNotFoundError` ではなく、何を先に実行すれば直るかをメッセージに含めます。

```python:scripts/build_suji_picks.py(抜粋)
def _require(path: Path, how_to_build: str) -> None:
    """入力ファイルが無いときは、作り方まで示して落とす。

    月次ジョブ (build_suji_table.py) や朝バッチ (build_index.py) が回っていない
    ときに、素の FileNotFoundError だけ出て原因が分からない状態を避ける。
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} が見つかりません。\n  {how_to_build}")

# 使う側
_require(path, "python scripts/build_suji_table.py を先に実行してください")
_require(path, f"python scripts/build_index.py --date {day:%Y-%m-%d} "
               f"--predictor {predictor_id} を先に実行してください")
```

`build_kimarite_probs.py` の係数ローダも、`kimarite_blend.load_pair_table()` も同じ形です。
「ファイルが無い」はパス文字列を見れば分かりますが、「そのファイルは誰が作るのか」はリポジトリの構造を知らないと分かりません。
依存順序は `run-daily-sync.sh` のステップ順としてしか存在しないので、エラーメッセージがそれを再現してくれると、深夜に Cloud Logging を見る人が助かります。

無言スキップと、作り方を示して落ちる、の使い分けは次のとおりです。

| 状況 | 挙動 | 理由 |
| --- | --- | --- |
| レース単位で前提が無い | `continue`(無言) | 直前バッチでは正常な状態。全体を止める理由がない |
| ファイル単位で前提が無い | 作り方付きで `raise` | 上流ジョブが回っていない。続けても全レースが空になる |
| ファイルはあるが形が古い | 理由付きで `raise` | 古い係数で静かに壊れるより止まるほうが安全 |

## 5. 失敗の型を分類する

ここまでの事故と、第 3 章で触れた直前情報の取りこぼしを合わせて、「エラーにならない失敗」を 5 つの型に分けます。

| 型 | 例 | 気づき方 | 対策 |
| --- | --- | --- | --- |
| 書いたのに消える | cone 外の出力先、`git add` の列挙漏れ(1 節) | リポジトリ内のファイルが更新されていない | 出力先を cone と `git add` の両方に足す。新しい出力先を足す PR で `run*.sh` を同時に更新する |
| 減っているのに動く | 学習母数 31% 欠落(2 節) | ログの範囲の左端が最古日とズレている | 母数と範囲をログに出し、一致すべき値との不変条件を決める |
| 古いまま動く | 係数 CSV のクラス構成が `CELLS` と不一致(3 節) | 落ちるので気づく | 構成が一致しなければ例外。学習と推論を CSV で分離し、検査可能にする |
| 片方だけ取れる | 結果 `bc_rs1_2` と払戻 `bc_rs2` が別々に公開される(第 3 章) | 結果はあるが払戻が無い行 | 独立に append し、次サイクルで補完。下流は JOIN で揃わない行を落とす |
| 無いのに 200 が返る | boatcast が存在しないファイルに HTTP 200 で SPA の HTML を返す(第 3 章) | 本文の先頭が `<` | すべてのフェッチャーで先頭文字を検査し、欠損として扱う |

最後の型について補足します。
`race.boatcast.jp` は CloudFront 経由で TSV を配信していますが、存在しないパスに対して 403/404 ではなく、SPA の `index.html` を 200 で返すことがあります。
`response.raise_for_status()` は通り、`response.text` には HTML が入ります。
TSV パーサに渡せば空の結果か例外になるはずですが、それは「パーサがたまたま厳しかった」だけです。
boatracecsv では `preview_tsv_scraper.py`、`result_realtime.py`、`payout_realtime.py`、`odds_realtime.py`、`monthly_schedule_scraper.py` のすべてが、
本文の先頭の非空白文字が `<` なら `None` を返して欠損扱いにします。

```python:scripts/boatrace/result_realtime.py(抜粋)
response.encoding = "utf-8"
body = response.text
if body.lstrip().startswith("<"):
    # CloudFront SPA fallback for missing files
    logging_module.debug("result_realtime_body_is_html", url=url)
    return None
return body
```

5 つの型に共通するのは、**成功の定義が「例外が出なかった」になっている**ことです。
`git add` が例外を出さない、`continue` は例外ではない、softmax は何を入れても確率を返す、HTTP 200 は成功、片方が取れたのは成功。
どれも局所的には正しく、全体としては壊れています。
対策も共通で、「成功していれば必ず成り立つ、外から確認できる条件」を 1 つ決めて、それを検査するか、ログに出して比較できるようにすることです。

## 6. 簡略版コード

2 節の不変条件と 3 節の係数検査を、合成データで動く形にまとめます。
実装の `CELLS` は 32 クラスですが、ここでは 4 クラスに縮めています。

```python:invariants.py
"""沈黙する失敗を「音を出す失敗」に変える 2 つの検査(簡略版)。

1. check_training_range : build_kimarite.py の `races=NNNNN (開始日 〜 終了日)` ログに
   相当する不変条件。左端が data/results/realtime/ の最古日と一致しなければ落とす。
2. load_coefficients    : build_kimarite_probs.py の係数ローダ。クラス構成が CELLS と
   一致しなければ落とす(古い係数で静かに壊れるのを防ぐ)。
"""
from __future__ import annotations

import csv
from pathlib import Path

# 実装は 32 クラス(boatrace.kimarite.CELLS)。ここでは 4 クラスに縮めている
CELLS: tuple[str, ...] = ("逃げ_1", "差し_2", "まくり_3", "その他_1")
RESULTS_DIR = Path("data") / "results" / "realtime"
CARDS_DIR = Path("data") / "programs" / "race_cards"


def collect_days(repo: Path) -> list[str]:
    """build_kimarite.collect() の骨格。race_cards が無い日は continue で黙って飛ぶ。"""
    days: list[str] = []
    for res_path in sorted((repo / RESULTS_DIR).glob("*/*/*.csv")):
        rel = res_path.relative_to(repo / RESULTS_DIR)
        if not (repo / CARDS_DIR / rel).exists():
            continue  # ← ここが沈黙する
        days.append(f"{rel.parts[0]}-{rel.parts[1]}-{res_path.stem}")
    return days


def oldest_result_day(repo: Path) -> str:
    """学習範囲の「あるべき左端」= results/realtime の最古日。"""
    first = sorted((repo / RESULTS_DIR).glob("*/*/*.csv"))[0]
    rel = first.relative_to(repo / RESULTS_DIR)
    return f"{rel.parts[0]}-{rel.parts[1]}-{first.stem}"


def check_training_range(repo: Path, days: list[str]) -> None:
    """不変条件: 学習ログの左端 == results/realtime の最古日。"""
    expected = oldest_result_day(repo)
    print(f"races={len(days)} ({min(days)} 〜 {max(days)})")
    if min(days) != expected:
        raise RuntimeError(
            f"学習範囲の左端 {min(days)} が results/realtime の最古日 {expected} と"
            f"一致しません。race_cards の sparse-checkout が欠けている可能性があります"
        )


def load_coefficients(path: Path) -> tuple[list[float], list[list[float]]]:
    """cell_coef_*.csv → (切片, 係数行列)。前提が崩れていたら作り方を示して落とす。"""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} が見つかりません。\n"
            f"  python scripts/build_kimarite.py を先に実行してください"
        )
    classes, intercept, weights = [], [], []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)  # ヘッダ
        for kind, cls_name, b, *vals in reader:
            if kind == "coef":
                classes.append(cls_name)
                intercept.append(float(b))
                weights.append([float(v) for v in vals])
    if tuple(classes) != CELLS:
        raise ValueError(
            f"{path}: クラス構成が CELLS と一致しません。\n"
            f"  係数 CSV が古い可能性があります。build_kimarite.py を再実行してください"
        )
    return intercept, weights
```

`results/realtime` に 2025/11〜2026/02 の 4 日分、`race_cards` に直近 2 か月分だけを置いた一時ディレクトリで動かすと、次のようになります。

```
== 不変条件 1: race_cards が直近 2 か月しか無い(cone 欠け) ==
races=2 (2026-01-01 〜 2026-02-01)
RuntimeError: 学習範囲の左端 2026-01-01 が results/realtime の最古日 2025-11-01 と一致しません。race_cards の sparse-checkout が欠けている可能性があります
== 不変条件 1: race_cards が全履歴ある ==
races=4 (2025-11-01 〜 2026-02-01)
== 不変条件 2: 古い係数(3 クラス) ==
ValueError: .../cell_coef_daily.csv: クラス構成が CELLS と一致しません。
  係数 CSV が古い可能性があります。build_kimarite.py を再実行してください
== 不変条件 2: ファイルが無い ==
FileNotFoundError: /nonexistent/cell_coef_daily.csv が見つかりません。
  python scripts/build_kimarite.py を先に実行してください
== 不変条件 2: 現行の係数(4 クラス) ==
intercepts: [-1.0, 0.0, 1.0, 2.0] weights rows: 4
```

`collect_days()` の `continue` は実装そのままです。
不変条件を足す前は、1 つ目のケースでも `races=2` と出て正常終了していました。
違いは `check_training_range()` の 4 行だけで、そこに「左端は何と一致すべきか」という知識が入っています。

:::message
実装の `build_kimarite.py` は、この章を書いている時点では `races=` の行を出力するだけで、一致検査は人が読む運用手順(`docs/operations.md`)になっています。
簡略版ではそれを例外に格上げしました。
月次ジョブで落とすべきか、警告に留めるべきかは、「落ちたときに誰が翌朝までに直せるか」で決まります。
boatracecsv は個人運用なので、この章の考え方に従えば落とすほうが一貫していますが、実際にそうするかは未定です。
:::

## 元資料

- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/operations.md — 「穴予想 `v9_suji` の運用」「穴予想 v10_kimarite の運用」「荒れ度メーターの運用」(依存順序、cone の広さと学習母数、再発検知、学習と推論の分離)
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md — 「sparse-checkout 対象」3 節、「`stage_files_failed`」トラブルシュート、「得点率早見 `tokuten_hayami` の追加」、「2 段階目 (race_cards) を分けている理由」「リソース目安」
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-monthly-weights.sh — `paths` 配列、2 段階目の `git sparse-checkout add`、末尾の `git add`
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run.sh — `sparse_paths` 配列
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/infra/run-daily-sync.sh — `build-index` → `build-kimarite-probs` → `build-kimarite-picks` のステップ順
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite.py — `collect()` の `continue`、`races=` ログ
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite_probs.py — 係数 CSV のローダと `CELLS` 一致検査、純 Python の softmax
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/kimarite.py — `CELLS` の凍結とその理由
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/kimarite_blend.py — `load_pair_table()` のセル欠落検査、`read_cell_probs()` のヘッダ名参照
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/git_operations.py — `stage_files()` の `check=True` と `stage_files_failed`
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_kimarite_picks.py、https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/build_suji_picks.py — 無言スキップと `_require()`
- https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/result_realtime.py — SPA の HTML を欠損として扱う判定(他のフェッチャーも同形)
- コミット `96db9614ab3`(2026-08-13)、`e817dcfdb0c`(2026-08-22、PR #8)、`afb9a8df901`(2026-08-22、PR #9)、`925b8e7e2b0`(2026-09-01)のメッセージ

## 演習

公開 CSV だけで、2 節の不変条件を自分の手で確かめてください。

1. 2026 年 8 月の各日について、`https://boatracecsv.github.io/data/results/realtime/2026/08/DD.csv` と `https://boatracecsv.github.io/data/programs/race_cards/2026/08/DD.csv` の両方を取得し、`レースコード` の集合を比べます。結果はあるが出走表が無いレース、その逆のレースがそれぞれ何件あるかを数え、`build_kimarite.py` の `collect()` と同じ条件(両方に存在し、`決まり手` が空でない)で残るレース数を `races=N (開始日 〜 終了日)` の形式で出力してください。存在しない日は 404 になるので読み飛ばします。
2. `https://boatracecsv.github.io/data/estimate/kimarite/tables/cell_coef_daily.csv` を取得し、`行種別 == "coef"` の行数が 32 で、`クラス` 列に `逃げ_1` が含まれることを検査する関数を書いてください。わざと 1 クラス削った CSV を渡して、例外が出ることも確かめます。
3. 自分のパイプラインで「入力が減っても成功終了する」箇所を 1 つ見つけ、母数と範囲をログに出し、それが何と一致すべきかを 1 行のコメントで書いてください。
