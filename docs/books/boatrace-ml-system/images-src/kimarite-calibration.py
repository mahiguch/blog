"""第 20 章: P(逃げ) の予測帯別 校正プロット(設計時 test 3,527 レース)。"""
from _style import *

bands = ["0.0–0.2", "0.2–0.3", "0.3–0.4", "0.4–0.5", "0.5–0.6", "0.6–0.7", "0.7–0.8", "0.8–1.0"]
n = [167, 320, 423, 526, 609, 671, 596, 215]
pred = [15.6, 25.7, 35.1, 45.1, 55.0, 65.0, 74.8, 83.4]
obs = [15.0, 27.5, 31.4, 38.4, 57.0, 67.4, 71.8, 80.9]

fig, ax = plt.subplots(figsize=(11.6, 9.4))
ax.plot([0, 100], [0, 100], color=GRAY, lw=1.2, ls="--", label="予測 = 実測(対角線)", zorder=1)
ax.fill_between([0, 100], [-3, 97], [3, 103], color=BG1, zorder=0, label="±3pt")
ax.plot(pred, obs, "-", color=NAVY, lw=1.5, zorder=2)
sizes = [40 + v / 4 for v in n]
ax.scatter(pred, obs, s=sizes, color=NAVY, zorder=3, edgecolor="white", lw=1)
# 最大のずれを強調
i = 3
ax.scatter([pred[i]], [obs[i]], s=sizes[i], color=RED, zorder=4, edgecolor="white", lw=1)
ax.plot([pred[i], pred[i]], [pred[i], obs[i]], color=RED, lw=1.5, ls=":", zorder=2)
ax.annotate("0.4–0.5 帯: −6.6pt(最大のずれ)\n予測 45.1% → 実測 38.4%", xy=(pred[i], obs[i]), xytext=(50, 18), color=RED,
            fontfamily=BOLD, ha="left", va="center", arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.2))
# 各点に帯と n
for p, o, k, b in zip(pred, obs, n, bands):
    if k == 526:
        continue
    if o >= p:   # 対角線の上側 → 左上に置く
        ax.text(p - 1.8, o + 1.8, f"{b}\nn = {k}", ha="right", va="bottom", fontsize=9.5, color="#111111")
    else:        # 下側 → 右下に置く
        ax.text(p + 1.8, o - 1.8, f"{b}\nn = {k}", ha="left", va="top", fontsize=9.5, color="#111111")
ax.set_xlim(5, 95)
ax.set_ylim(5, 95)
ax.set_aspect("equal")
ticks = [10, 20, 30, 40, 50, 60, 70, 80, 90]
ax.set_xticks(ticks); ax.set_yticks(ticks)
ax.set_xticklabels([f"{t}%" for t in ticks]); ax.set_yticklabels([f"{t}%" for t in ticks])
ax.set_xlabel("予測帯内の P(逃げ) 予測平均")
ax.set_ylabel("実測の逃げ率")
ax.set_title("設計時 test 3,527 レース: 8 帯中 7 帯が ±3pt 以内", fontfamily=BOLD, loc="left")
ax.legend(loc="upper left", frameon=False)
ax.grid(color=BG2, lw=1)
ax.set_axisbelow(True)
save(fig, "kimarite-calibration.png")
