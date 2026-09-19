"""HTML/SVG 図版を headless Chrome(device-scale-factor 2)で PNG にする。

使い方: python render.py <name> [<name> ...]
  <name>.html を読み、先頭付近の <!-- size: WxH --> で CSS ピクセルの
  ウィンドウサイズを決める。出力は images/boatrace-ml-system/<name>.png。
  余白は pillow で白基準に trim し、20px(2x で 40px)のパディングを付ける。
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRC = Path(__file__).resolve().parent
OUT = SRC.parents[3] / "images" / "boatrace-ml-system"


def render(name: str) -> None:
    html = SRC / f"{name}.html"
    text = html.read_text(encoding="utf-8")
    m = re.search(r"<!--\s*size:\s*(\d+)x(\d+)\s*-->", text)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (800, 600)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "shot.png"
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={w},{h}", "--force-device-scale-factor=2",
             f"--screenshot={tmp}", html.as_uri()],
            check=True, capture_output=True,
        )
        img = Image.open(tmp).convert("RGB")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bbox = ImageChops.difference(img, bg).getbbox()
    if bbox:
        pad = 40
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad))
        img = img.crop(bbox)
    if img.width < 1600:  # 仕様: 幅 1600px 以上
        canvas = Image.new("RGB", (1600, img.height), (255, 255, 255))
        canvas.paste(img, ((1600 - img.width) // 2, 0))
        img = canvas
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.png"
    img.save(out, optimize=True)
    print(f"{out} {img.width}x{img.height} {out.stat().st_size/1024:.0f}KB")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        render(n)
