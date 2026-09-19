"""第 19 章: 名目被覆率 vs 実被覆率(正規 / Student-t)と σ 五分位別の被覆。"""
import numpy as np
from _style import *

nominal = [50, 80, 95]
normal = [53.5, 83.0, 95.6]
student = [49.6, 80.7, 95.8]

fig = plt.figure(figsize=(11, 5.4))
gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.32)

ax = fig.add_subplot(gs[0, 0])
ax.plot([40, 100], [40, 100], color=GRAY, lw=1.2, ls="--", label="名目 = 実被覆")
ax.plot(nominal, normal, "-o", color="#8AA0D0", lw=2.2, ms=8, label="正規分布")
ax.plot(nominal, student, "-s", color=NAVY, lw=2.5, ms=8, label="Student-t(df 9.14)")
for x, a, b in zip(nominal, normal, student):
    ax.text(x - 1.5, a + 1.3, f"{a:.1f}%", ha="right", va="bottom", color="#5B77B8", fontsize=10.5)
    ax.text(x + 1.5, b - 1.3, f"{b:.1f}%", ha="left", va="top", color=NAVY, fontsize=10.5, fontfamily=BOLD)
ax.set_xlim(42, 100)
ax.set_ylim(42, 100)
ax.set_xticks(nominal)
ax.set_xticklabels(["50%", "80%", "95%"])
ax.set_yticks([50, 60, 70, 80, 90, 100])
ax.set_yticklabels([f"{v}%" for v in [50, 60, 70, 80, 90, 100]])
ax.set_xlabel("名目被覆率")
ax.set_ylabel("実被覆率(テスト窓 47,000 艇走)")
ax.set_title("正規は 50% 区間が広すぎる、Student-t は全水準 ±1pt", fontfamily=BOLD, fontsize=12, loc="left")
ax.legend(loc="lower right", frameon=False)
ax.grid(color=BG2, lw=1)
ax.set_axisbelow(True)

# 挿図: σ 五分位別の被覆(名目 50%)
axi = fig.add_subplot(gs[0, 1])
cats = ["最安定\n五分位", "最不安定\n五分位"]
per_racer = [48.7, 51.8]
fixed = [57.2, 44.8]
x = np.arange(2)
w = 0.34
axi.bar(x - w / 2, fixed, width=w, color="#B9C6E4", label="帯幅一定")
axi.bar(x + w / 2, per_racer, width=w, color=NAVY, label="選手別 σ")
for i in range(2):
    axi.text(x[i] - w / 2, fixed[i] + 0.8, f"{fixed[i]:.1f}%", ha="center", va="bottom", fontsize=10.5, color="#5B77B8")
    axi.text(x[i] + w / 2, per_racer[i] + 0.8, f"{per_racer[i]:.1f}%", ha="center", va="bottom", fontsize=10.5, color=NAVY, fontfamily=BOLD,
             bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
axi.axhline(50, color=RED, lw=1.2, ls="--", label="名目 50%")
axi.set_xticks(x)
axi.set_xticklabels(cats)
axi.set_xlim(-0.55, 1.55)
axi.set_ylim(30, 65)
axi.set_yticks([30, 40, 50, 60])
axi.set_yticklabels(["30%", "40%", "50%", "60%"])
axi.set_ylabel("50% 区間の実被覆率")
axi.set_title("σ 五分位別(名目 50%)", fontfamily=BOLD, fontsize=12, loc="left")
axi.legend(loc="upper right", frameon=False, fontsize=10)
axi.grid(axis="y", color=BG2, lw=1)
axi.set_axisbelow(True)
save(fig, "slit-sim-band-coverage.png")
