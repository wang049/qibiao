"""生成前端/窗口用的应用图标（与页头 .mark 同色）。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "electrical_krow" / "frontend"
NAVY = (0x1E, 0x3A, 0x4C, 255)
ACCENT = (0x1F, 0x6F, 0x8A, 255)
WHITE = (255, 255, 255, 255)
MUTED = (0x8F, 0xB8, 0xC4, 255)


def paint(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = round(size * 0.08)
    radius = round(size * 0.22)
    draw.rounded_rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=radius,
        fill=NAVY,
    )
    inner = size - 2 * margin
    left = margin + round(inner * 0.16)
    right = size - margin - round(inner * 0.16)
    header_top = margin + round(inner * 0.18)
    header_h = max(round(size * 0.08), 2)
    draw.rounded_rectangle(
        [left, header_top, right, header_top + header_h],
        radius=max(header_h // 2, 1),
        fill=ACCENT,
    )
    row_h = max(round(size * 0.07), 2)
    gap = max(round(size * 0.045), 1)
    top = header_top + header_h + gap + max(round(size * 0.02), 1)
    for i in range(3):
        y = top + i * (row_h + gap)
        draw.rounded_rectangle(
            [left, y, right, y + row_h],
            radius=max(row_h // 2, 1),
            fill=WHITE,
        )
        if size >= 32:
            tick = max(round(size * 0.028), 1)
            cx = left + round((right - left) * 0.12)
            cy = y + row_h // 2
            draw.ellipse(
                [cx - tick, cy - tick, cx + tick, cy + tick],
                fill=ACCENT if i == 0 else MUTED,
            )
    return img


def supersample(size: int) -> Image.Image:
    return paint(size * 4).resize((size, size), Image.Resampling.LANCZOS)


def write_icns(png: Path, dest: Path) -> None:
    iconset = dest.with_suffix(".iconset")
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    src = Image.open(png)
    for name, edge in {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }.items():
        src.resize((edge, edge), Image.Resampling.LANCZOS).save(iconset / name)
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(dest)],
            check=True,
        )
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


def main() -> int:
    FRONT.mkdir(parents=True, exist_ok=True)
    png = FRONT / "app-icon.png"
    ico = FRONT / "app-icon.ico"
    icns = FRONT / "app-icon.icns"
    master = supersample(1024)
    master.save(png)
    master.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    write_icns(png, icns)
    print(png)
    print(ico)
    print(icns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
