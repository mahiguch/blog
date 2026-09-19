---
title: "付録: CSV スキーマ早見表と参照リンク"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 本文で使った用語(偏差値pt・寄与・収縮・log-loss・Brier など)の定義を 1〜2 文で引き直せる |
| システム | boatracecsv が配信する全 CSV の一覧と更新頻度、レースコードとパスの規約。列定義そのものは各ファイルのドキュメントへのリンクで示す |

この付録は本文を読みながら引くための早見表です。列の定義は boatracecsv の `docs/data/` に
すでに書かれているので、ここでは繰り返さず、ファイルごとの「主な列」とリンクだけを載せます。
一覧は 2026 年 9 月時点のリポジトリ(`data/` 配下の実ディレクトリ)と照合しています。

## 1. データファイル一覧

すべて `https://boatracecsv.github.io/` をルートに、パスを連結すればダウンロードできます
(例: `https://boatracecsv.github.io/data/results/realtime/2026/05/06.csv`)。
更新頻度の「2 分毎」は Cloud Run Jobs の `preview-realtime` (JST 08:00〜22:59)、
「日次」は `daily-sync` (JST 07:30)、「月次」は `monthly-weights` (毎月 1 日 JST 06:00) による更新です(第 11 章)。

### 1.1 事前情報(`data/programs/`)

| ファイル | パス | 更新 | 主な列 | 詳細 |
| --- | --- | --- | --- | --- |
| Race Title | `data/programs/title/YYYY/MM/DD.csv` | 日次 | `レースコード` `レース場コード` `レース場` `タイトル` `日次` `グレード` `レース名` `電話投票締切予定` | [programs.md#race-title](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#race-title) |
| Race Cards | `data/programs/race_cards/YYYY/MM/DD.csv` | 日次 | `艇N_登録番号` `艇N_級別` `艇N_F本数` `艇N_全国平均ST` `艇N_全国勝率` `艇N_モーター番号` `艇N_モーター2連対率` `艇N_節D{D}走{S}_{進入,ST,着順}` | [programs.md#race-cards](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#race-cards) |
| Waku10 | `data/programs/waku10/YYYY/MM/DD.csv` | 日次 | `艇N_枠番別勝率` `艇N_枠番別平均ST` `艇N_過去{n}走_{着順,進入,グレード}` | [programs.md#waku10](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#waku10-枠番別過去10走) |
| Monthly Schedule | `data/programs/monthly_schedule/YYYY/MM.csv` | 日次(月ファイルを上書き) | `場コード` `節開始日` `節終了日` `グレード` `タイトル` `レース数` | [programs.md#monthly-schedule](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#monthly-schedule-月間開催日程) |
| Recent National Form | `data/programs/recent_national/YYYY/MM/DD.csv` | 日次 | `艇N_前K節_{開始日,終了日,場コード,グレード,着順列}`(K=1..5) | [programs.md#recent-national-form](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#recent-national-form) |
| Recent Local Form | `data/programs/recent_local/YYYY/MM/DD.csv` | 日次 | 同上(当地の 5 節のみ) | [programs.md#recent-local-form](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#recent-local-form) |
| Motor Stats | `data/programs/motor_stats/YYYY/MM/DD.csv` | 日次(開催場のみ) | `記録日` `モーター期起算日` `場コード` `モーター番号` `勝率` `2連対率` `3連対率` `出走数` `平均ラップ秒` | [programs.md#motor-stats](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#motor-stats) |
| Motor History | `data/programs/motor_history/YYYY/MM/DD.csv`(日付 = 基準節終了日) | 日次(節終了ごとに追記) | `場コード` `基準節終了日` `モーター番号` `使用開始日` `使用終了日` `使用者名` `着順列` | [programs.md#motor-history](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md#motor-history-モーター履歴) |

### 1.2 直前情報(`data/previews/`)

締切 5 分前のスナップショットをソース別に 1 レース 1 行で追記します。先頭 6 列
(`レースコード` `レース日` `レース場` `レース回` `締切時刻` `取得日時`)は全ファイル共通です(第 3 章)。

| ファイル | パス | 更新 | 主な列 | 詳細 |
| --- | --- | --- | --- | --- |
| tkz | `data/previews/tkz/YYYY/MM/DD.csv` | 2 分毎 | 6 艇 × `体重(kg)` `体重調整(kg)` `展示タイム` `チルト` | [previews.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md) |
| stt | `data/previews/stt/YYYY/MM/DD.csv` | 2 分毎 | 6 艇 × `コース` `スタート展示`(F は負値、L は空欄) | 同上 |
| sui | `data/previews/sui/YYYY/MM/DD.csv` | 2 分毎 | `気象観測時刻` `風速(m)` `風向` `波の高さ(cm)` `天候` `気温(℃)` `水温(℃)` | 同上 |
| original_exhibition | `data/previews/original_exhibition/YYYY/MM/DD.csv` | 2 分毎 | `計測項目1〜3` + 6 艇 × `値1〜3`(江戸川は配信なし) | 同上 |
| 得点率早見 | `data/previews/tokuten_hayami/YYYY/MM/DD.csv` | 2 分毎(予選最終日まで) | `ボーダー順位` `1着点〜6着点` + 6 艇 × `得点率` `順位` `k着時得点率` | [previews.md#得点率早見](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md#得点率早見-tokuten_hayami) |
| od1 | `data/previews/od1/YYYY/MM/DD.csv` | 2 分毎 | 3 連複 20 列、拡連複 15 × `下限`/`上限`、`単勝_1〜6`、複勝 6 × `下限`/`上限` | [previews.md#オッズの注意点](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md#オッズod1--od2--od3の注意点) |
| od2 | `data/previews/od2/YYYY/MM/DD.csv` | 2 分毎 | 2 連単 30 列、2 連複 15 列 | 同上 |
| od3 | `data/previews/od3/YYYY/MM/DD.csv` | 2 分毎 | 3 連単 120 列(`3連単_1-2-3` 〜 `3連単_6-5-4`) | 同上 |

オッズは集計中の値で確定オッズではなく、`0.0` は「まだ投票がない」を意味します。

### 1.3 結果(`data/results/`)

| ファイル | パス | 更新 | 主な列 | 詳細 |
| --- | --- | --- | --- | --- |
| Realtime Results | `data/results/realtime/YYYY/MM/DD.csv` | 2 分毎(締切 +3 分以降、終日キャッチアップ) | `決まり手`、`N着_艇番` `N着_選手名` `N着_レースタイム`、`Nコース_艇番` `Nコース_スタートタイミング` `Nコース_F`、気象 6 列 | [results.md#realtime-results](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md#realtime-results) |
| Realtime Payouts | `data/results/payouts/YYYY/MM/DD.csv` | 2 分毎(同上) | 券種ごとの `_組番` `_払戻金` `_人気`(単勝 / 複勝 / 2 連単 / 2 連複 / 拡連複 / 3 連単 / 3 連複) | [results.md#realtime-payouts](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md#realtime-payouts) |

### 1.4 派生(`data/estimate/`)

| ファイル | パス | 更新 | 主な列 | 詳細 |
| --- | --- | --- | --- | --- |
| Strength Index | `data/estimate/{predictor_id}/YYYY/MM/DD.csv` | 日次 + 2 分毎(`状態` 列で区別) | `状態`、`N枠_{枠番,選手,モーター,展示,気象}pt`、`N枠_寄与_{要素}pt`、`N枠_強さpt` | [estimate.md#strength-index](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md#strength-index) |
| Racer ST | `data/estimate/racer_st/YYYY/MM/DD.csv`(状態は `racer_st/state.csv`) | 日次 | `N枠_登録番号` `N枠_推定ST` `N枠_推定ST_p25` `N枠_推定ST_p75` | [estimate.md#racer-st](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md#racer-st) |
| Motor pt 内訳(1 走 1 行) | `data/estimate/motor_pt/runs/YYYY/MM/DD.csv` | 日次 | `節` `走行日` `級別` `グレード分類` `進入` `生得点` `セルμ` `セルσ` `残差z` `減衰重み` | [motor_pt.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_pt.md) |
| Motor pt 内訳(1 モーター 1 行) | `data/estimate/motor_pt/motors/YYYY/MM/DD.csv` | 日次 | `節数` `走数` `Σw` `Σw2` `n_eff` `加重平均残差` `素点` | 同上 |
| Motor pt ベースライン | `data/estimate/motor_pt/baseline/YYYY/MM/DD.csv` | 日次 | `級別` `グレード分類` `進入` `μ` `σ` `サンプル数` | 同上 |
| Motor Ability Score | `data/estimate/motor_ability_score.csv`、`motor_ability_score_v4.csv` | 静的 | `級別` `グレード分類` `1着pt〜6着pt` | [motor_ability_score.md](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_ability_score.md) |
| 荒れ度メーター 日次 | `data/estimate/kimarite/YYYY/MM/DD.csv` | 日次 + 2 分毎 | `状態` `荒れ度` `P_{クラス}` × 32 | [estimate.md#荒れ度メーター](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md#荒れ度メーター決まり手セルモデル) |
| 荒れ度メーター 係数 | `data/estimate/kimarite/tables/cell_coef_{daily,realtime}.csv` | 月次 | `median` / `center` / `scale` / `coef` × 32 の行 | 同上 |
| Stage2 ペア表 | `data/estimate/kimarite/tables/pair_table.csv` | 月次 | `セル` `2着コース` `3着コース` `n` `確率`(640 行) | 同上 |
| 穴予想の買い目(v10_kimarite) | `data/estimate/kimarite/picks/YYYY/MM/DD.csv` | 日次 + 2 分毎 | `状態` `買い目1〜5` `決まり手1〜5` `確率1〜5` | 同上 |
| 穴予想 A/B の log-loss | `data/estimate/kimarite/tables/logloss.csv` | 月次 | `集計月` `n` `PL_logloss` `ブレンド_logloss` `改善nat` `95%CI下限` `95%CI上限` | 同上 |
| 荒れ度の校正 | `data/estimate/kimarite/tables/calibration.csv` | 月次 | `予測帯` `n` `予測荒れ度` `実測荒れ度` `差pt` `logloss` | 同上 |
| スジ表 | `data/estimate/suji/tables/suji_table.csv` | 月次 | `場コード` `1着コース` `2着コース` `3着コース` `n` `確率`(120 行) | [estimate.md#穴予想-v9_suji](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md#穴予想-v9_suji-スジ表と買い目) |
| 決まり手注釈 | `data/estimate/suji/tables/kimarite_table.csv` | 月次 | 出目ごとの `最頻決まり手` と `逃げ` 〜 `恵まれ` の構成比 | 同上 |
| 穴予想の買い目(v9_suji) | `data/estimate/suji/YYYY/MM/DD.csv` | 停止(2026-08-22 退役) | `1着コース` `1着艇番` `買い目1〜5` `決まり手1〜5` | 同上 |
| 場 × 季節 × コース勝率 | `data/estimate/stadium/win_rate.csv` | 静的 | `場コード` `季節` `1コース勝率〜6コース勝率` | [estimate.md#stadium-parameters](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md#stadium-parameters) |
| 場 × レース番号 × コース 1 着率 | `data/estimate/stadium/course_win_rate.csv` | 月次 | `場コード` `レース回` `n` `1コース勝率〜6コース勝率`(収縮済み、288 行) | 同上 |
| 気象回帰係数 | `data/estimate/stadium/sui_params.csv` | 静的(再学習スクリプトあり) | `base_c1〜c6`、`wave_cm_*` `temp_diff_*` `wind_tail_ms_*` `wind_head_ms_*` `is_cloudy_*` `is_rainy_*` | 同上 |
| 場別重み | `data/estimate/stadium/weights/{predictor_id}/YYYY-MM.csv` | 月次 | `stadium` `n_samples` `mu_{key}` `sigma_{key}` `w_{key}` `r2` `fallback` | 同上 |

`{predictor_id}` は 2026 年 9 月時点で `v1_basic` 〜 `v10_kimarite` の 10 個で、active なのは
`v1_basic` と `v10_kimarite` の 2 つです(第 10 章)。退役した予想者のディレクトリも過去分は残っています。

:::message
`docs/data/README.md` の一覧表には Racer ST、`motor_ability_score_v4.csv`、`calibration.csv` が
載っていませんが、いずれも個別ドキュメントに定義があり、`data/` にも実在します(2026 年 9 月時点)。
上の表はディレクトリの実態に合わせて補っています。
:::

## 2. レースコードとパスの規約

### 2.1 レースコード

全 CSV の共通キーは 12 桁のレースコード `YYYYMMDDjjrr` です。

| 部分 | 桁 | 意味 | 例 |
| --- | ---: | --- | --- |
| `YYYYMMDD` | 8 | レース日 | `20260801` |
| `jj` | 2 | 場コード(`01` 桐生 〜 `24` 大村、第 1 章) | `10`(三国) |
| `rr` | 2 | レース番号(`01` 〜 `12`) | `01` |

`202608011001` は 2026-08-01 の三国 1R です。事前情報・直前情報・結果・派生のどれも
この列で JOIN できます(第 2 章)。pandas で読むときは `dtype={"レースコード": str}` を
指定し、先頭ゼロや桁落ちを防いでください。

### 2.2 パスと列名の規約

| 規約 | 内容 |
| --- | --- |
| 日次ファイル | `YYYY/MM/DD.csv`。1 ファイルにその日の全場・全レースが入る |
| 月次ファイル | `monthly_schedule/YYYY/MM.csv`(月間日程)、`weights/{predictor_id}/YYYY-MM.csv`(重み)。区切りの有無が違う点に注意 |
| 日付の意味が違うもの | `motor_history` の日付は実行日ではなく**基準節終了日** |
| 静的テーブル | `data/estimate/stadium/*.csv`、`data/estimate/{suji,kimarite}/tables/*.csv`、`motor_ability_score*.csv`。日付パーティションを持たず、上書き更新される |
| 場コードの列名 | 事前情報・派生は `レース場コード`(title は `レース場` に場名)、直前情報・結果は `レース場` に 2 桁コード。いずれも `01`〜`24` のゼロ詰め |
| レース番号の表記 | title / race_cards は `1R`、直前情報・結果は `01R`、`course_win_rate.csv` は整数 `1` |
| 列の接頭辞 | 事前情報は `艇N_`(艇番順)、派生の index は `N枠_`、結果は `N着_`(着順)と `Nコース_`(実進入コース順) |
| `状態` 列 | index / 荒れ度 / 買い目の CSV は 1 レースにつき `daily` 行と `realtime` 行の最大 2 行を持つ。回収率の母数は `realtime` 行のみ |
| 追記の単位 | 直前情報・結果は「同一レースコードは 1 日 1 行」のルールで per-source に追記(第 3 章) |

## 3. 用語集

本文の用語を、初出の章とともに 1〜2 文でまとめます。

**レースの用語**

| 用語 | 定義 |
| --- | --- |
| 艇番・枠番 | 出走表で決まる 1〜6 の番号。艇色(1 白 2 黒 3 赤 4 青 5 黄 6 緑)と対応する(第 1 章) |
| コース | スタート時に艇が並ぶ位置。内側から 1〜6 コースで、枠番と一致するとは限らない。本書の特徴量は多くをコースに紐付ける(第 1 章・第 4 章) |
| 枠なり・前付け | 枠番どおりにコースに入るのが枠なり、外の艇が内のコースを取りにいくのが前付け。1 号艇が 1 コースに入る割合は約 98% |
| スタート展示 | 本番前に同じ手順で行う試走。ここで分かる進入コースが `previews/stt` の `コース` で、本書のモデルはこれを進入の基準にする(第 1 章・第 3 章) |
| ST(スタートタイミング) | 大時計 0 秒からスタートライン通過までの秒数。小さいほど早い。全国平均 ST の `0.00` は「実績なし」で、最速ではない(第 1 章・第 18 章) |
| F(フライング) | 0 秒より前にラインを通過した失格。着順の代わりに `F`、ST は負値で記録される。`F本数` は選手の累積本数 |
| L(出遅れ) | 大きく遅れたスタート。結果 CSV に専用マークは無く、大きな ST として数値で入る。`stt` では空欄 |
| 1 マーク | スタート後の最初のターンマーク。ここでの攻防でほぼ勝敗が決まる(第 15 章) |
| 決まり手 | 1 着の取り方の 6 分類(逃げ / 差し / まくり / まくり差し / 抜き / 恵まれ)。逃げ以外の平均配当は逃げの 4〜6 倍で、穴予想の予測対象になる(第 1 章・第 20 章) |
| スリット・スリット隊形 | スタートラインを通過する瞬間の 6 艇の前後関係。本番 ST から作ると結果を強く規定するが、締切前には再現できない(第 19 章) |
| 節 | 1 つの開催。数日から最長 7 日で、`節開始日`〜`節終了日` で識別する。節間成績や「直近 5 節」「直近 6 節」の単位 |
| 級別 | 選手の格付け A1 / A2 / B1 / B2。A1 が最上位。モーター指数のスコア表の行キーにもなる(第 5 章) |
| グレード | 開催の格。SG / PG1 / G1 / G2 / G3 / 一般(IP)。モーター指数では `SG_G1` と `G2_G3_一般` の 2 分類に丸める |
| モーター期 | モーターの使用期間。`モーター期起算日` で切り替わり、期をまたぐ履歴は指数の計算から除外する(第 5 章) |

**特徴量とモデルの用語**

| 用語 | 定義 |
| --- | --- |
| 偏差値pt | 素点を場別の平均 μ・標準偏差 σ で標準化し `50 + 10 × z` にした値。枠番pt・選手pt・モーターpt・展示pt・気象pt はすべてこのスケール(第 4 章) |
| 寄与 | 各要素の重み w × 偏差値pt。`N枠_寄与_{要素}pt` 列で、強さpt を要素別に分解した内訳(第 7 章・第 16 章) |
| 強さpt | 寄与 5 つの合計。Σw = 1 なので平均 50・標準偏差 10 のスケールに収まり、この順位で買い目を組む(第 7 章・第 8 章) |
| 重み | 場ごとに非負制約付き最小二乗(SLSQP)で学習する各要素の係数。`weights/{predictor_id}/YYYY-MM.csv` に月次で保存(第 7 章) |
| daily | 朝の日次バッチで計算した状態。進入は枠なり仮定、展示・気象は中立値 50 で暫定(第 1 章・第 11 章) |
| realtime | 締切 5 分前の直前バッチで引き直した状態。展示進入と展示・気象の実測値で強さpt が確定する。回収率の母数はこの行だけ |
| 予想者(predictor) | 特徴量セットと買い目の作り方を固定した 1 つの予想。`v1_basic` のように ID を持ち、レジストリで管理する(第 10 章) |
| control | A/B 実験の対照となる予想者。本書では `v1_basic`。新しい予想者は control と同一レースでペア比較して判定する(第 9 章・第 10 章) |
| 退役 | 予想者の `status` を `retired` に変えて配信を止めること。ID は再利用せず、過去データも残す(第 10 章) |
| 収縮(ベイズ収縮) | サンプルが少ない推定値を事前分布(平均や上位のプール)へ引き戻す操作。`n / (n + k)` の形で、k が大きいほど強く縮む。モーター指数(k=10)、コース 1 着率(k=50)、ST 推定、Stage2 ペア表(k=150)で使う(第 5 章・第 18 章・第 21 章) |
| EWMA・半減期 | 古い観測ほど重みを指数的に減らす加重平均。半減期 60 日(モーター)や 30 日(ST)で「何日で重みが半分になるか」を指定する(第 5 章・第 18 章) |
| n_eff(有効サンプル数) | 重み付きサンプルの実効的な件数 `(Σw)² / Σw²`(Kish)。収縮の強さを決める n に使う(第 5 章) |
| 荒れ度 | `1 − P(逃げ_1)`。決まり手 × 1 着コースの 32 クラス多項ロジスティック回帰から出す「1 コース以外が勝つ確率」(第 20 章) |
| スジ表 | 1 着コースを与えたときの 2・3 着コースの条件付き確率 `P(R2, R3 | R1)`。全場プールの 120 行(第 21 章) |

**評価の用語**

| 用語 | 定義 |
| --- | --- |
| 買い目・点数 | 実際に買う 3 連単の出目と、その本数。点数を増やせば的中率は上がるが購入額も増える(第 8 章) |
| 的中率 | 的中レース数 ÷ 母数。母数は 1〜3 着が揃い、直前の買い目が組めたレースだけで、返還・中止・不成立は分子分母とも除外する(第 9 章) |
| 回収率 | 払戻合計 ÷ 購入額合計。本当に知りたい値だが分散が極端に大きく、予想者どうしの差を有意にするには数か月から数年かかる(第 9 章) |
| 万舟 | 100 円あたり 10,000 円以上の配当。レースの 16.3% だが払戻総額の 67.6% を占める(2025-11〜2026-08、n = 42,090、第 1 章)。本数ではなく 1 万円あたりで比べる(第 17 章) |
| log-loss | 正解に割り当てた確率の負の対数の平均(単位 nat)。小さいほど良い。分散が小さく、少ないレースで決着するため本書の主判定指標(第 9 章) |
| Brier | 予測確率と実績(0/1)の二乗誤差の平均。log-loss と並べて校正の良さを見る補助指標で、コース 1 着率の収縮強度 k の選定に使った(第 9 章) |
| 校正 | 予測確率の平均が実測の頻度と合っていること。荒れ度メーターは予測帯ごとに ±5pt 以内を KPI にする(第 20 章) |
| ペア比較 | 同一レースで 2 つの予想者の結果を突き合わせて差を取る比較。非ペアの信頼区間より狭くなり、control との有意差を判定できる(第 9 章) |
| Plackett-Luce | 強さから順位の確率分布を作るモデル。強さpt に β=1.4 を掛けて 3 連単 120 通りの分布にし、穴予想の対照や ブレンドの片側に使う(第 21 章) |

## 4. 参照リンク

**boatracecsv(Python: 収集・特徴量・モデル・CSV 配信)**

- リポジトリ: https://github.com/BoatraceCSV/boatracecsv.github.io(MIT License)
- 配信ルート: https://boatracecsv.github.io/
- [`docs/README.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/README.md) — ドキュメントの入口
- [`docs/data/README.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/README.md) — ファイル一覧と関係図
- [`docs/data/programs.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md) / [`previews.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md) / [`results.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md) / [`estimate.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) / [`motor_pt.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_pt.md) / [`motor_ability_score.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_ability_score.md) — 各 CSV の列定義
- [`docs/development.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/development.md) / [`operations.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/operations.md) / [`infrastructure.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md) — 開発・運用・Cloud Run Jobs(第 11 章・第 12 章)
- 設計書: [`docs/design/motor_ability_index_v2.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/motor_ability_index_v2.md)(第 5 章)、[`course_strength_v6.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/course_strength_v6.md)(第 10 章)、[`st_estimation.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/st_estimation.md)(第 18 章)、[`slit_tenkai.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/slit_tenkai.md)(第 19 章)、[`ana_prediction.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/design/ana_prediction.md)(第 9 章・第 20 章・第 21 章)
- [`scripts/boatrace/predictors/registry.py`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/scripts/boatrace/predictors/registry.py) — 予想者レジストリの単一情報源(第 10 章)

**fun-site(TypeScript / Astro: 予想ページの生成と配信)**

- リポジトリ: https://github.com/BoatraceCSV/fun-site(MIT License)
- 公開サイト: https://boatrace-fun.net
- [`docs/architecture.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/architecture.md) — 全体構成(第 0 章・第 13 章)
- [`docs/domain.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md) — ドメイン知識と各 pt の再現手順(第 1 章・第 16 章)
- [`docs/batch.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/batch.md) / [`web.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/web.md) / [`infrastructure.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/infrastructure.md) / [`operations.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/operations.md) — バッチ・Web・インフラ・運用(第 13 章・第 14 章・第 17 章)
- [`packages/shared/src/predictors.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/predictors.ts) — 予想者定義の TypeScript 側(第 14 章)
- [`packages/shared/src/constants/stadiums.ts`](https://github.com/BoatraceCSV/fun-site/blob/main/packages/shared/src/constants/stadiums.ts) — 24 場のコードと名前

**その他**

- Boatrace OpenAPI: https://github.com/BoatraceOpenAPI — boatracecsv の README が、最新情報が必要な場合の別ソースとして案内しているもの

## 元資料

- boatracecsv [`docs/data/README.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/README.md) — ファイル一覧表、関係図、URL の構造
- boatracecsv [`docs/data/programs.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/programs.md) — 事前情報 8 ファイルの列定義
- boatracecsv [`docs/data/previews.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/previews.md) — 直前情報 8 ソースの列定義と取得ルール
- boatracecsv [`docs/data/results.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/results.md) — 結果・払戻金の列定義
- boatracecsv [`docs/data/estimate.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/estimate.md) — レジストリのパス規約、Strength Index、Racer ST、スジ表、荒れ度メーター、場別パラメータ
- boatracecsv [`docs/data/motor_pt.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_pt.md) / [`motor_ability_score.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/data/motor_ability_score.md) — モーターpt 内訳とスコア表
- boatracecsv [`docs/infrastructure.md`](https://github.com/BoatraceCSV/boatracecsv.github.io/blob/main/docs/infrastructure.md) — 3 つのジョブの実行時刻
- fun-site [`docs/domain.md`](https://github.com/BoatraceCSV/fun-site/blob/main/docs/domain.md) — 的中率・回収率の母数、決まり手、艇色
