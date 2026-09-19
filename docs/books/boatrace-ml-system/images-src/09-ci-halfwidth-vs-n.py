"""第 9 章: 95%CI 半幅と n の関係(回収率差 / log-loss 差)。"""
import numpy as np
from _style import *

n = np.logspace(2, 6, 400)
N_TEST = 3527

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8.4), sharex=True)
fig.subplots_adjust(hspace=0.16)

# 上段: 回収率差
hw1 = 1.96 * 403 / np.sqrt(n)
ax1.plot(n, hw1, color=NAVY, lw=2.5, label="95%CI 半幅 = 1.96 × 403 / √n")
for eff, npt, lab, dur, xy in [(4.2, 34_700, "観測された差 +4.2pt", "8.2 か月", (34_700 * 1.6, 12)),
                               (2.0, 153_000, "2.0pt を検出", "36 か月", (153_000 * 0.14, 0.95))]:
    ax1.axhline(eff, color=RED, lw=1.3, ls="--")
    ax1.text(110, eff * 1.12, lab, color=RED, va="bottom", fontsize=11)
    ax1.plot([npt], [eff], "o", color=RED, ms=8, zorder=5)
    ax1.annotate(f"n ≈ {npt:,}({dur})", xy=(npt, eff), xytext=xy, color=RED, fontfamily=BOLD,
                 ha="left", va="center", arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.2))
ax1.set_yscale("log")
ax1.set_ylim(0.5, 120)
ax1.set_yticks([1, 2, 4.2, 13.3, 50, 100])
ax1.set_yticklabels(["1", "2", "4.2", "13.3", "50", "100"])
ax1.set_ylabel("回収率差の 95%CI 半幅(pt)")
ax1.set_title("回収率差:効果 +4.2pt に届くのは n ≈ 34,700(8.2 か月)", fontfamily=BOLD, loc="left", pad=30)
ax1.legend(loc="upper right", frameon=False)
# 横軸上部の注記(1 日 = 141 レース)
tr = ax1.get_xaxis_transform()  # x: data, y: axes
for xv, lab in [(141, "1 日 = 141 レース"), (34_700, "8.2 か月"), (153_000, "36 か月")]:
    ax1.plot([xv, xv], [1.0, 1.04], color=GRAY, lw=1.2, transform=tr, clip_on=False)
    ax1.text(xv, 1.06, lab, ha="center", va="bottom", color=GRAY, fontsize=10.5, transform=tr)
ax1.plot([100, 1e6], [1.0, 1.0], color=GRAY, lw=0.8, transform=tr, clip_on=False)

# 下段: log-loss 差
hw2 = 1.96 * 0.503 / np.sqrt(n)
ax2.plot(n, hw2, color=NAVY, lw=2.5, label="95%CI 半幅 = 1.96 × 0.503 / √n")
ax2.axhline(0.0961, color=RED, lw=1.3, ls="--")
ax2.text(1.5e4, 0.0961 * 1.12, "観測された改善 +0.0961 nat", color=RED, va="bottom", fontsize=11)
ax2.plot([105], [0.0961], "o", color=RED, ms=8, zorder=5)
ax2.annotate("n ≈ 105(半幅基準)", xy=(105, 0.0961), xytext=(180, 0.028), color=RED, fontfamily=BOLD,
             ha="left", va="center", arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.2))
ax2.plot([418], [0.0961 / 2], "o", color=RED, ms=8, zorder=5, mfc="white", mew=2)
ax2.annotate("n ≈ 418(全幅基準、半幅 = 0.048)", xy=(418, 0.0961 / 2), xytext=(1200, 0.17), color=RED, fontfamily=BOLD,
             ha="left", va="center", arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.2))
ax2.set_yscale("log")
ax2.set_ylim(0.0007, 0.25)
ax2.set_yticks([0.001, 0.0166, 0.0961])
ax2.set_yticklabels(["0.001", "0.0166", "0.0961"])
ax2.set_ylabel("log-loss 差の 95%CI 半幅(nat)")
ax2.set_title("3 連単 log-loss 差:効果 +0.0961 nat には n ≈ 100〜400 で届く", fontfamily=BOLD, loc="left")
ax2.legend(loc="lower left", frameon=False)
ax2.set_xscale("log")
ax2.set_xlim(100, 1e6)
ax2.set_xticks([1e2, 1e3, 1e4, 1e5, 1e6])
ax2.set_xticklabels(["100", "1,000", "10,000", "100,000", "1,000,000"])
ax2.set_xlabel("n(レース数、対数目盛)")

# test 期間の縦点線
for ax in (ax1, ax2):
    ax.axvline(N_TEST, color=GRAY, lw=1.5, ls=(0, (3, 3)))
    ax.grid(color=BG2, lw=1)
    ax.set_axisbelow(True)
ax1.text(N_TEST * 1.08, 60, "test 期間\nn = 3,527\n(半幅 ±13.3pt)", color=GRAY, va="top", fontsize=10.5)
ax2.text(N_TEST * 1.08, 0.075, "test 期間\nn = 3,527\n(半幅 ±0.0166)", color=GRAY, va="top", fontsize=10.5)
save(fig, "09-ci-halfwidth-vs-n.png")
