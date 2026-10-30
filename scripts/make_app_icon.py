"""把 frontend/app-icon.png 收成窗口用的 ico / icns。

主图是 HORSE 与 EECD。改图标时替换这张 png，再运行本脚本。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

FRONT = Path(__file__).resolve().parents[1] / "electrical_krow" / "frontend"


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
    png = FRONT / "app-icon.png"
    ico = FRONT / "app-icon.ico"
    icns = FRONT / "app-icon.icns"
    if not png.is_file():
        raise SystemExit(f"缺少图标：{png}")
    master = Image.open(png).convert("RGBA")
    if master.size != (1024, 1024):
        master = master.resize((1024, 1024), Image.Resampling.LANCZOS)
        master.save(png)
    master.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    write_icns(png, icns)
    print(png)
    print(ico)
    print(icns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
