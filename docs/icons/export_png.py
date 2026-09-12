#!/usr/bin/env python3
"""Export logo SVG to PNG/ICO for packaging and window icons."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent
ICONS = ROOT / "icons"
OUT_PNG = ROOT / "png"


def render_svg(svg_path: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def main() -> int:
    # Minimal QGuiApplication for icon/image painting
    QGuiApplication(sys.argv[:1])
    OUT_PNG.mkdir(parents=True, exist_ok=True)

    logo = ICONS / "logo.svg"
    mark = ICONS / "logo-mark.svg"
    if not logo.exists():
        print("logo.svg missing", file=sys.stderr)
        return 1

    for src, stem in ((logo, "logo"), (mark, "logo-mark")):
        for size in (16, 24, 32, 48, 64, 128, 256):
            img = render_svg(src, size)
            path = OUT_PNG / f"{stem}-{size}.png"
            img.save(str(path), "PNG")
            print(path.name)

    # Linux / AppImage convenience aliases (icon name "etools")
    for size in (16, 24, 32, 48, 64, 128, 256):
        src = OUT_PNG / f"logo-{size}.png"
        if src.exists():
            shutil.copyfile(src, OUT_PNG / f"etools-{size}.png")

    # Multi-size ICO via QIcon
    icon = QIcon(str(logo))
    icon_path = OUT_PNG / "etools.ico"
    # QImageWriter ICO is unreliable across Qt builds — stitch with Pillow if available
    try:
        from PIL import Image

        sizes = [16, 24, 32, 48, 64, 128, 256]
        pil_images = []
        for size in sizes:
            png = OUT_PNG / f"logo-{size}.png"
            pil_images.append(Image.open(png).convert("RGBA"))
        pil_images[0].save(
            icon_path,
            format="ICO",
            sizes=[(s, s) for s in sizes],
            append_images=pil_images[1:],
        )
        print(icon_path.name)
    except Exception as exc:
        # Fallback: save largest as PNG only
        print(f"ICO skipped ({exc}); use logo-256.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
