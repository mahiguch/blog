"""第 7 章: 偏差値pt × 重み = 寄与 → 強さpt の分解(2026-08-01 桐生 1R 1枠 daily 行)。"""
from _style import *
import matplotlib.patches as mpatches

names = ["枠番", "選手", "モーター", "展示", "気象"]
pts = [67.5, 38.3, 41.6, 50.0, 50.0]
ws = [0.36, 0.22, 0.12, 0.21, 0.08]
contrib = [24.4, 8.6, 5.0, 10.6, 4.2]
total = 52.7
colors = NAVY_TINTS

fig = plt.figure(figsize=(11, 5.4))
gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.05)

# 左: 表
axl = fig.add_subplot(gs[0, 0])
axl.set_axis_off()
cols = ["成分", "偏差値pt", "×", "重み w", "=", "寄与"]
xs = [0.02, 0.30, 0.47, 0.60, 0.77, 0.90]
y0 = 0.90
dy = 0.13
axl.text(0.5, 1.0, "偏差値pt × 重み = 寄与", ha="center", va="center", fontfamily=BOLD, fontsize=13, transform=axl.transAxes)
for x, c in zip(xs, cols):
    axl.text(x, y0, c, ha="left" if x < 0.9 else "right", va="center", color=GRAY, fontsize=11, transform=axl.transAxes)
axl.plot([0.0, 1.0], [y0 - 0.055, y0 - 0.055], color=GRAY, lw=1, transform=axl.transAxes, clip_on=False)
for i, (nm, p, w, c) in enumerate(zip(names, pts, ws, contrib)):
    y = y0 - dy * (i + 1)
    axl.add_patch(mpatches.Rectangle((0.0, y - 0.05), 0.04, 0.10, color=colors[i], transform=axl.transAxes, clip_on=False))
    axl.text(0.06, y, nm, ha="left", va="center", transform=axl.transAxes)
    axl.text(0.30, y, f"{p:.1f}", ha="left", va="center", transform=axl.transAxes)
    axl.text(0.47, y, "×", ha="left", va="center", color=GRAY, transform=axl.transAxes)
    axl.text(0.60, y, f"{w:.2f}", ha="left", va="center", transform=axl.transAxes)
    axl.text(0.77, y, "=", ha="left", va="center", color=GRAY, transform=axl.transAxes)
    axl.text(0.90, y, f"{c:.1f}", ha="right", va="center", fontfamily=BOLD, transform=axl.transAxes)
y = y0 - dy * 6
axl.plot([0.0, 1.0], [y + 0.065, y + 0.065], color=GRAY, lw=1, transform=axl.transAxes, clip_on=False)
axl.text(0.06, y, "合計 = 強さpt", ha="left", va="center", fontfamily=BOLD, transform=axl.transAxes)
axl.text(0.60, y, "1.00", ha="left", va="center", color=GRAY, transform=axl.transAxes)
axl.text(0.90, y, f"{total:.1f}", ha="right", va="center", fontfamily=BOLD, color=RED, transform=axl.transAxes)
axl.set_xlim(0, 1)
axl.set_ylim(0, 1)

# 右: 積み上げ横棒
axr = fig.add_subplot(gs[0, 1])
left = 0.0
for i, (nm, c) in enumerate(zip(names, contrib)):
    axr.barh(0, c, left=left, color=colors[i], edgecolor="white", lw=1.5, height=0.5)
    txtcolor = "white" if i < 2 else "#111111"
    if c >= 8:
        axr.text(left + c / 2, 0, f"{c:.1f}", ha="center", va="center", color=txtcolor, fontsize=11)
        axr.text(left + c / 2, 0.30, nm, ha="center", va="bottom", fontsize=10, color="#111111")
    else:
        # 細いセグメントは棒の上に名前と値をまとめて置く(高さを交互にずらす)
        ytxt = 0.30 if i % 2 == 0 else 0.50
        axr.text(left + c / 2, ytxt, f"{nm}\n{c:.1f}", ha="center", va="bottom", fontsize=10, color="#111111")
        axr.plot([left + c / 2, left + c / 2], [0.25, ytxt - 0.02], color=GRAY, lw=0.8)
    left += c
axr.axvline(50, color=GRAY, lw=1, ls=":")
axr.text(49.3, 0.62, "平均 50", ha="right", va="bottom", color=GRAY, fontsize=10)
axr.annotate(f"強さpt {total:.1f}", xy=(total + 0.3, -0.2), xytext=(total + 1.5, -0.55), color=RED, fontfamily=BOLD, fontsize=13,
             ha="left", va="center", arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.2))
axr.plot([total, total], [-0.28, 0.28], color=RED, lw=2)
axr.set_xlim(0, 64)
axr.set_ylim(-0.8, 0.95)
axr.set_yticks([])
axr.spines["left"].set_visible(False)
axr.set_xlabel("寄与の積み上げ(pt)")
axr.set_title("寄与を積み上げると強さpt", fontfamily=BOLD)
fig.text(0.5, -0.02, "index CSV 2026-08-01 桐生 1R 1枠(daily 行)の値。寄与は小数第 2 位で丸めてあるので合計は ±0.1 ずれることがある",
         ha="center", va="top", color=GRAY, fontsize=10)
save(fig, "07-contribution-decomposition.png")
