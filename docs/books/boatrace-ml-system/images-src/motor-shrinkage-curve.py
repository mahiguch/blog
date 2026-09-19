"""第 5 章: 収縮係数 n_eff/(n_eff+k) の曲線。"""
import numpy as np
from _style import *

n = np.linspace(0, 60, 601)
fig, ax = plt.subplots(figsize=(9, 5.2))
ax.plot(n, np.ones_like(n), color=GRAY, lw=2, ls=":", label="k = 0(収縮なし、常に 1)")
ax.plot(n, n / (n + 10), color=NAVY, lw=3, label="k = 10(採用値)")
ax.plot(n, n / (n + 50), color="#8AA0D0", lw=2, label="k = 50")

# 採用値の目印: n_eff=10 で 0.5
ax.plot([10], [0.5], "o", color=NAVY, ms=8)
ax.plot([0, 10], [0.5, 0.5], color=NAVY, lw=1, ls="--")
ax.plot([10, 10], [0, 0.5], color=NAVY, lw=1, ls="--")
ax.annotate("n_eff = 10 で 0.5", xy=(10, 0.5), xytext=(14, 0.36), color=NAVY,
            arrowprops=dict(arrowstyle="-", color=NAVY, lw=1))

# 実データの中央値
med = 34.6
ax.axvline(med, color=RED, lw=1.5, ls=(0, (4, 3)))
ax.text(med - 0.8, 0.04, "2026-08-22 実データの\nn_eff 中央値 34.6", color=RED, va="bottom", ha="right")
ax.plot([med], [med / (med + 10)], "o", color=RED, ms=7)
ax.annotate(f"{med/(med+10):.2f}", xy=(med, med / (med + 10)), xytext=(med + 2.5, med / (med + 10) - 0.09),
            color=RED, fontfamily=BOLD)

ax.set_xlim(0, 60)
ax.set_ylim(0, 1.05)
ax.set_xlabel("n_eff(Kish の有効サンプル数)")
ax.set_ylabel("収縮係数  n_eff / (n_eff + k)")
ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
ax.grid(axis="y", color=BG2, lw=1)
ax.legend(loc="lower right", frameon=False)
save(fig, "motor-shrinkage-curve.png")
