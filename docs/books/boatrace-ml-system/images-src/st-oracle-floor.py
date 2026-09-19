"""第 18 章: B0〜M3、オラクル、−10% 基準の MAE 数直線。"""
from _style import *

pts = [("B0", 0.0526), ("M1", 0.0511), ("M2", 0.0507), ("M3", 0.0505)]
oracle = 0.0486
crit = 0.0473

fig, ax = plt.subplots(figsize=(11, 4.6))
y = 0
ax.axhline(y, color="#111111", lw=1.5, zorder=1)
ax.set_xlim(0.0464, 0.0532)
ax.set_ylim(-1.75, 1.9)
# 目盛
ticks = [0.047, 0.048, 0.049, 0.050, 0.051, 0.052, 0.053]
ax.set_xticks(ticks)
ax.set_xticklabels([f"{t:.3f}" for t in ticks])
ax.set_yticks([])
for s in ("left", "top", "right", "bottom"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="x", length=6)
ax.set_xlabel("テスト窓 MAE(秒、左ほど良い)")

# モデル点(ラベルは上下交互)
offsets = {"B0": 0.45, "M1": 0.45, "M2": -0.45, "M3": 0.45}
for name, v in pts:
    ax.plot([v], [y], "o", color=NAVY, ms=11, zorder=5)
    dy = offsets[name]
    ax.text(v, dy, f"{name}\n{v:.4f}", ha="center", va="bottom" if dy > 0 else "top", color=NAVY, fontfamily=BOLD, fontsize=11.5)
# オラクル
ax.plot([oracle], [y], "D", color=RED, ms=11, zorder=5)
ax.text(oracle, 0.45, f"オラクル\n{oracle:.4f}", ha="center", va="bottom", color=RED, fontfamily=BOLD, fontsize=11.5)
ax.text(oracle, -0.42, "選手平均型の理論下限\n(テスト窓の実測平均を使った参照値)", ha="center", va="top", color=RED, fontsize=10)
ax.axvline(oracle, ymin=0.30, ymax=0.70, color=RED, lw=1, ls=":")
# −10% 基準
ax.plot([crit], [y], "x", color=GRAY, ms=14, mew=3, zorder=5)
ax.text(crit, 0.45, f"−10% 基準\n{crit:.4f}", ha="center", va="bottom", color=GRAY, fontfamily=BOLD, fontsize=11.5)
ax.text(crit, 1.05, "オラクルより左 = 到達不能", ha="center", va="bottom", color=GRAY, fontsize=10)

# 寸法線
def dim(x0, x1, yy, label, color):
    ax.annotate("", xy=(x0, yy), xytext=(x1, yy), arrowprops=dict(arrowstyle="<->", color=color, lw=1.4, shrinkA=0, shrinkB=0))
    ax.text((x0 + x1) / 2, yy + (0.06 if yy > 0 else -0.08), label, ha="center", va="bottom" if yy > 0 else "top", color=color, fontsize=11)
    for xx in (x0, x1):
        ax.plot([xx, xx], [yy - 0.1, yy + 0.1], color=color, lw=1)

dim(oracle, 0.0526, 1.25, "B0 → オラクル 0.0040", RED)
dim(0.0505, 0.0526, -1.15, "B0 → M3 0.0021(ギャップの 53%)", NAVY)
save(fig, "st-oracle-floor.png")
