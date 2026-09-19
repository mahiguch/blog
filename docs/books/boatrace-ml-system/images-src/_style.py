"""Shared matplotlib style for book figures.

Usage:  from _style import *   (sets rcParams, exports colors and OUT dir)
Run each script with the python that has matplotlib installed, e.g.
    python docs/books/boatrace-ml-system/images-src/<name>.py
Output goes to images/boatrace-ml-system/<name>.png
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NAVY = "#2B4C9B"
RED = "#E5002D"
GRAY = "#6B7280"
BG1 = "#EEF2FF"
BG2 = "#F3F4F6"
# secondary tints (derived from navy) for stacked series
NAVY_TINTS = ["#2B4C9B", "#5B77B8", "#8AA0D0", "#B9C6E4", "#D9E0F2"]

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "images" / "boatrace-ml-system"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "Hiragino Sans",
    "font.size": 12,
    "axes.titlesize": 13,
    "axes.labelsize": 12,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 11,
    "axes.edgecolor": GRAY,
    "axes.labelcolor": "#111111",
    "xtick.color": "#111111",
    "ytick.color": "#111111",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.unicode_minus": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})
BOLD = "Hiragino Sans W6"


def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.15)
    print("saved", path)
