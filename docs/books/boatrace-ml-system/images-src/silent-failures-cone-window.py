"""第 12 章: 8 か月窓の cone と全履歴の結果ファイル(月別の帯グラフ)。"""
from _style import *
import matplotlib.patches as mpatches

months = []
y, m = 2025, 5
while (y, m) <= (2026, 9):
    months.append((y, m))
    m += 1
    if m == 13:
        y, m = y + 1, 1
idx = {ym: i for i, ym in enumerate(months)}
N = len(months)

results_start = idx[(2025, 11)]
cards_start = idx[(2025, 5)]
cone_before = (idx[(2026, 1)], idx[(2026, 8)])  # inclusive
target = idx[(2026, 9)]

fig, ax = plt.subplots(figsize=(12, 6.6))
rows = {"results": 4.3, "cards_before": 2.8, "cards_after": 1.35}
H = 0.7

def cell(row, i, filled, color):
    ax.add_patch(mpatches.Rectangle((i, row - H / 2), 1, H,
                                    facecolor=color if filled else "white", edgecolor=color if filled else GRAY,
                                    lw=1.2, ls="-" if filled else (0, (3, 2)), zorder=2))

# 上段: results/realtime は 2025/11 から全月ある
for i in range(cards_start, results_start):
    ax.add_patch(mpatches.Rectangle((i, rows["results"] - H / 2), 1, H, facecolor="white", edgecolor=BG2, lw=1, zorder=1))
ax.add_patch(mpatches.Rectangle((results_start, rows["results"] - H / 2), target - results_start, H, facecolor=NAVY, edgecolor="white", lw=1.2, zorder=2))
# 中段: race_cards 修正前(存在: 2025/05〜、cone: 2026/01〜08 だけ)
for i in range(cards_start, target):
    filled = cone_before[0] <= i <= cone_before[1]
    cell(rows["cards_before"], i, filled, NAVY if filled else GRAY)
# 下段: 修正後(2025/11〜 が塗られる)
for i in range(cards_start, target):
    filled = i >= results_start
    cell(rows["cards_after"], i, filled, RED if filled else GRAY)

# ループ矢印: results の各月 → race_cards(修正前 cone)。無い月は continue
y_top = rows["results"] - H / 2 - 0.03
y_bot = rows["cards_before"] + H / 2 + 0.03
for i in range(results_start, target):
    has_cards = cone_before[0] <= i <= cone_before[1]
    xc = i + 0.5
    col = NAVY if has_cards else RED
    ax.annotate("", xy=(xc, y_bot), xytext=(xc, y_top),
                arrowprops=dict(arrowstyle="-|>", color=col, lw=1.4, shrinkA=0, shrinkB=0), zorder=3)
    if not has_cards:
        ax.text(xc, (y_top + y_bot) / 2, "continue", ha="center", va="center", color=RED, fontsize=9, rotation=90,
                fontfamily=BOLD, bbox=dict(facecolor="white", edgecolor="none", pad=0.5), zorder=4)

# 対象月 2026/09 の列
ax.add_patch(mpatches.Rectangle((target, rows["cards_after"] - H / 2 - 0.1), 1, rows["results"] - rows["cards_after"] + H + 0.2,
                                facecolor=BG2, edgecolor="none", zorder=0))
ax.text(target + 0.5, (rows["results"] + rows["cards_after"]) / 2, "対象月(9/1 実行)", ha="center", va="center", color=GRAY, fontsize=10, rotation=90)

# 行ラベル(左)
ax.text(-0.3, rows["results"], "data/results/realtime\n(全履歴、2025/11〜)", ha="right", va="center", fontsize=11)
ax.text(-0.3, rows["cards_before"], "data/programs/race_cards\n修正前の cone(8 か月窓)", ha="right", va="center", fontsize=11)
ax.text(-0.3, rows["cards_after"], "data/programs/race_cards\n修正後の cone(sparse-checkout add)", ha="right", va="center", fontsize=11, color=RED)

# 帯の注記
ax.text(cone_before[0] + 4, rows["cards_before"], "cone に入っている 8 か月\n(2026/01〜08)", ha="center", va="center", color="white", fontsize=10)
ax.text(results_start + 5, rows["cards_after"], "results/realtime の実ディレクトリから月を列挙して\ngit sparse-checkout add → 2025/11〜 が揃う", ha="center", va="center", color="white", fontsize=10)
ax.text((cards_start + results_start) / 2, rows["cards_before"] - H / 2 - 0.08, "リポジトリには存在(2025/05〜)\nが cone の外", ha="center", va="top", color=GRAY, fontsize=9.5)
ax.text((cards_start + results_start) / 2, rows["cards_after"] - H / 2 - 0.08, "results より前は参照されない", ha="center", va="top", color=GRAY, fontsize=9.5)

# ループの説明(上)
ax.text(cards_start, rows["results"] + H / 2 + 0.12, "build_kimarite.py のループ: results の各日 → 同日の race_cards を読む → 無ければ continue(無言で飛ばす)",
        ha="left", va="bottom", color="#111111", fontsize=10.5)

# 母数の注記(右)
ax.text(N + 0.2, rows["cards_before"], "学習母数\n30,160 レース", ha="left", va="center", color=NAVY, fontsize=11, fontfamily=BOLD)
ax.text(N + 0.2, rows["cards_after"], "学習母数\n43,595 レース", ha="left", va="center", color=RED, fontsize=11, fontfamily=BOLD)
ax.text(N + 0.2, (rows["cards_before"] + rows["cards_after"]) / 2, "欠落 13,435 レース\n= 31%", ha="left", va="center", color=GRAY, fontsize=10)

ax.set_xlim(-0.2, N + 3.4)
ax.set_ylim(0.5, 5.3)
ax.set_xticks([i + 0.5 for i in range(N)])
ax.set_xticklabels([f"{y}\n{m:02d}" if m == 1 or i == 0 else f"{m:02d}" for i, (y, m) in enumerate(months)], fontsize=10)
ax.set_yticks([])
for s in ("left", "top", "right"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="x", length=0)
save(fig, "silent-failures-cone-window.png")
