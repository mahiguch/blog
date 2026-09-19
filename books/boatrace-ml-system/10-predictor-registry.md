---
title: "予想者レジストリと A/B 実験"
---

## この章で学ぶこと

| 観点 | 内容 |
| --- | --- |
| ML | 1 成分だけ差し替えて比較する実験設計、control の固定、退役判定、負け方の分析 |
| システム | 宣言的なレジストリ、追加は 1 エントリ・退役は status 変更だけ、ID の不再利用、2 リポジトリ間の同期 |

## 1. 予想者(predictor)という単位

- `PredictorSpec`: id / display_name / slot / status / started_at / component_keys
- `__post_init__` が未登録の成分キーや重複を弾く
- `--all-active` が registry をループし、index 生成・weights 学習・GCS ミラーが自動で追従する
- 簡略版コード(frozen dataclass、50 行)

## 2. 運用ルール

- 退役は `status="retired"` に変えるだけ。過去データとロジックは残す
- ID は退役後も再利用しない(累計回収率の同一性)
- fun-site の `predictors.ts` と ID を同期する

## 3. v1〜v10 の系譜(2026-08 時点)

| ID | 仮説 | 結果 |
| --- | --- | --- |
| v1_basic | 5 成分の線形合成 | control。現在も active |
| v2_tenkai | motor → 公式 2 連対率 | 有意差なし、07-19 退役 |
| v3_tenkai | 進入変更の有利度を 6 成分目に | 有意差なし、07-19 退役 |
| v4_motor | モーター指数をエキスパート評価で調整 | +0.30pt、p=0.884、08-10 退役 |
| v5_slit | 予測 ST を AI 推定 ST に | −2.72pt、p=0.377、08-10 退役 |
| v6_course | 枠番pt を場 × レース番号のコース強度に | −6.91pt、p=0.0047、08-09 退役 |
| v7_aggregate | v4 + v5 + v6 の全部入り | −7.76pt、p=0.0040、08-09 退役 |
| v8_aionly | v7 と同一で買い目選定だけ変更 | −10.62pt、p=0.0001、08-09 退役 |
| v9_suji | 穴予想 A案(スジ表) | 08-22 退役(スロット重複) |
| v10_kimarite | 穴予想 B案(決まり手モデル) | active |

## 4. 負け方を分析する

- v6 / v7 / v8 の共通差分は `waku → course`。course を持たない v4 / v5 は control 同水準なので、course 成分が主因と特定
- ただし 3 者は course を共有するので独立検定ではなく「course 仮説を 1 回否定した」重み
- 点数分布を control に揃えても v6 は 77.5%。「点数ではなく選定そのものの問題」と切り分け
- 「全部入り」は効果が直交する見込みで投入したが、悪い成分が 1 つあれば全部沈む

## 5. v9 の退役は成績劣化ではない

- 本番 1,511 レースで A案 70.7% / B案 68.8%、買い目の重なり平均 2.70 点 / 5 点
- 確率モデルを持ち主判定(log-loss)に載る B案を残した。体験指標(平均配当 3,949 円 vs 3,035 円)では A案が上

## 元資料

- `scripts/boatrace/predictors/registry.py`、`docs/data/estimate.md`(現行レジストリと退役ノート)
- `docs/design/course_strength_v6.md` 末尾、`docs/design/aggregate_v7.md` §5、`docs/operations.md`

## 演習

新しい予想者 `v11_xxx` を registry に追加し、`build_index.py --predictor v11_xxx` で 1 日分の index を生成する。

## 執筆メモ

- 系譜の表は本書で最も引用される表になる。時点(2026-08)と n を必ず添える。
