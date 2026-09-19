"""第 7 章: 24 場の重み(weights/v1_basic/2026-08.csv)の積み上げ棒。"""
import numpy as np
import pandas as pd
from _style import *

CSV = "/Users/mahiguch/dev/boatracecsv.github.io/data/estimate/stadium/weights/v1_basic/2026-08.csv"
NAMES = ("桐生 戸田 江戸川 平和島 多摩川 浜名湖 蒲郡 常滑 津 三国 びわこ 住之江 "
         "尼崎 鳴門 丸亀 児島 宮島 徳山 下関 若松 芦屋 福岡 唐津 大村").split()
df = pd.read_csv(CSV)
df = df.set_index("stadium").loc[NAMES]  # 場コード順
cols = ["w_waku", "w_racer", "w_motor", "w_exhibit", "w_weather"]
labels = ["枠番 w_waku", "選手 w_racer", "モーター w_motor", "展示 w_exhibit", "気象 w_weather"]
colors = NAVY_TINTS
highlight = {"戸田", "福岡", "江戸川"}

fig, ax = plt.subplots(figsize=(12, 5.6))
x = np.arange(len(NAMES))
bottom = np.zeros(len(NAMES))
for c, lab, col in zip(cols, labels, colors):
    v = df[c].to_numpy()
    ax.bar(x, v, bottom=bottom, color=col, edgecolor="white", lw=0.8, width=0.72, label=lab)
    bottom += v

# ハイライト: 赤枠 + 太字ラベル
for i, nm in enumerate(NAMES):
    if nm in highlight:
        ax.bar(i, 1.0, color="none", edgecolor=RED, lw=2.2, width=0.86, zorder=5)
        # 枠番 / 気象 / 展示 の値を注記
        ytxt = 1.075 if nm == "江戸川" else 1.02
        ax.text(i, ytxt, f"枠番 {df.loc[nm,'w_waku']:.3f}", ha="center", va="bottom", fontsize=9.5, color=RED)

ticklabels = [f"{i+1:02d}\n{nm}" if i % 2 == 0 else f"{i+1:02d}\n\n{nm}" for i, nm in enumerate(NAMES)]
ax.set_xticks(x)
ax.set_xticklabels(ticklabels, fontsize=10)
for lab, nm in zip(ax.get_xticklabels(), NAMES):
    if nm in highlight:
        lab.set_fontfamily(BOLD)
        lab.set_color(RED)
ax.set_ylim(0, 1.15)
ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
ax.set_ylabel("重み(合計 1)")
ax.set_xlabel("レース場(場コード順)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=5, frameon=False, fontsize=11)
ax.grid(axis="y", color=BG2, lw=1, zorder=0)
ax.set_axisbelow(True)
fig.text(0.5, -0.09, "weights/v1_basic/2026-08.csv(学習窓 2026-02-01〜2026-07-31)。赤枠は本文で取り上げた戸田・福岡・江戸川",
         ha="center", va="top", color=GRAY, fontsize=10)
save(fig, "07-weights-by-stadium.png")
