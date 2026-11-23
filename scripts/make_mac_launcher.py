"""生成 macOS 双击启动器 Report2Excel.app（仿 CardMaker make_mac_launcher.py）。

运行：.venv/bin/python scripts/make_mac_launcher.py
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ICON_PNG = ROOT / "src" / "report2excel" / "gui" / "assets" / "icon.png"
APP = ROOT / "Report2Excel.app"

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Report2Excel</string>
  <key>CFBundleDisplayName</key><string>Report2Excel</string>
  <key>CFBundleIdentifier</key><string>dev.liuzhiyuan.report2excel</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleExecutable</key><string>Report2Excel</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
"""

LAUNCHER = """#!/bin/bash
exec "{python}" -m report2excel.gui
"""


def draw_icon(size: int = 1024) -> Image.Image:
    """翡翠绿渐变圆角底 + 白色表格卡片 + 黄色高亮行 + 绿色验算徽章。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = Image.new("RGBA", (size, size))
    top, bottom = (16, 185, 129), (4, 120, 87)
    draw_bg = ImageDraw.Draw(bg)
    for y in range(size):
        t = y / size
        col = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,)
        draw_bg.line([(0, y), (size, y)], fill=col)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, size - 40, size - 40], radius=220, fill=255)
    img.paste(bg, (0, 0), mask)

    # 阴影与白色表格纸张
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([220, 220, 804, 830], radius=56, fill=(0, 0, 0, 85))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)))

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([210, 200, 794, 810], radius=56, fill=(255, 255, 255, 255))
    # 深色表头
    d.rounded_rectangle([258, 256, 746, 336], radius=18, fill=(30, 58, 95, 255))
    # 正常行 + 黄色警告高亮行 + 正常行
    d.rounded_rectangle([258, 366, 746, 440], radius=14, fill=(241, 245, 249, 255))
    d.rounded_rectangle([258, 466, 746, 540], radius=14, fill=(254, 240, 138, 255))
    d.rounded_rectangle([258, 566, 746, 640], radius=14, fill=(241, 245, 249, 255))
    d.rounded_rectangle([258, 666, 746, 740], radius=14, fill=(226, 232, 240, 255))
    # 表格竖向分隔线
    for x in (470, 610):
        d.line([(x, 366), (x, 740)], fill=(255, 255, 255, 255), width=10)

    # 右下角验算对勾圆章
    d.ellipse([650, 650, 860, 860], fill=(15, 23, 42, 255), outline=(255, 255, 255, 255), width=14)
    d.line([(710, 758), (746, 794), (806, 720)], fill=(52, 211, 153, 255), width=22, joint="curve")
    return img


def build_icns(png: Path, target: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        source = Image.open(png)
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = base * scale
                name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
                source.resize((px, px), Image.Resampling.LANCZOS).save(iconset / name)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)


def main() -> None:
    ICON_PNG.parent.mkdir(parents=True, exist_ok=True)
    draw_icon().save(ICON_PNG)
    if APP.exists():
        shutil.rmtree(APP)
    (APP / "Contents" / "MacOS").mkdir(parents=True)
    (APP / "Contents" / "Resources").mkdir(parents=True)
    (APP / "Contents" / "Info.plist").write_text(INFO_PLIST, encoding="utf-8")
    launcher = APP / "Contents" / "MacOS" / "Report2Excel"
    launcher.write_text(LAUNCHER.format(python=ROOT / ".venv" / "bin" / "python"), encoding="utf-8")
    launcher.chmod(0o755)
    build_icns(ICON_PNG, APP / "Contents" / "Resources" / "AppIcon.icns")
    print(f"已生成 {APP}")


if __name__ == "__main__":
    main()
