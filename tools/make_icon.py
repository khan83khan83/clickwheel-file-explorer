"""Draw the app icon and pack it into a multi-size .ico.

    python tools/make_icon.py

The mark is three covers fanned in perspective — the Cover Flow motif the app is
built around — on a deep blue squircle. Detail is deliberately minimal: anything
finer than the card silhouettes turns to mush at 16px.

Writes assets/icons/app.ico plus a 256px PNG for previewing.
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt          # noqa: E402
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter,  # noqa: E402
                           QPainterPath, QPen)
from PySide6.QtWidgets import QApplication                       # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
OUT_DIR = ROOT / "assets" / "icons"

BG_TOP = "#3D7BFF"
BG_BOT = "#1B3FA8"
CARD = "#FFFFFF"
CARD_EDGE = "#D8E2F5"


def draw_card(p: QPainter, s: float, cx: float, cy: float, w: float, h: float,
              angle: float, scale: float, opacity: float, detail: bool) -> None:
    p.save()
    p.translate(cx * s, cy * s)
    p.rotate(angle)
    p.scale(scale, scale)
    p.setOpacity(opacity)

    r = QRectF(-w * s / 2, -h * s / 2, w * s, h * s)
    radius = max(1.0, s * 0.022)

    if opacity > 0.9:
        # Layered translucent rects approximate a blur; a single offset rect
        # just reads as a hard bar under the card.
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(4):
            grow = s * 0.006 * (i + 1)
            p.setBrush(QColor(10, 24, 64, 26 - i * 5))
            p.drawRoundedRect(
                r.adjusted(-grow, -grow + s * 0.012, grow, grow + s * 0.014),
                radius + grow, radius + grow)

    p.setBrush(QColor(CARD))
    p.setPen(QPen(QColor(CARD_EDGE), max(0.5, s * 0.004)))
    p.drawRoundedRect(r, radius, radius)

    # Two hint lines, only where they will actually be visible.
    if detail and s >= 48:
        p.setPen(QPen(QColor("#9DB4DE"), max(1.0, s * 0.016),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        y0 = r.top() + r.height() * 0.34
        for i, frac in enumerate((0.52, 0.34)):
            y = y0 + i * r.height() * 0.15
            p.drawLine(QPointF(r.left() + r.width() * 0.18, y),
                       QPointF(r.left() + r.width() * (0.18 + frac), y))
    p.restore()


def render(size: int) -> QImage:
    s = float(size)
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # Squircle background.
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0.0, QColor(BG_TOP))
    g.setColorAt(1.0, QColor(BG_BOT))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, s, s), s * 0.225, s * 0.225)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(path)

    # Keep the cards inside the squircle.
    p.setClipPath(path)

    cw, ch = 0.29, 0.41
    detail = size >= 48
    # Tucked closer and turned less than before: at a wide angle the rotated
    # rectangles stop reading as covers and start looking like banners.
    draw_card(p, s, 0.355, 0.500, cw, ch, -10.0, 0.84, 0.42, False)
    draw_card(p, s, 0.645, 0.500, cw, ch, 10.0, 0.84, 0.42, False)
    draw_card(p, s, 0.500, 0.492, cw, ch, 0.0, 1.0, 1.0, detail)

    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def pack_ico(images: dict, path: Path) -> None:
    """Build an .ico with PNG-compressed entries (supported since Vista)."""
    entries, blobs = [], []
    offset = 6 + 16 * len(images)
    for size in sorted(images):
        data = images[size]
        dim = 0 if size >= 256 else size        # 0 means 256 in the ICO header
        entries.append(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                                   len(data), offset))
        blobs.append(data)
        offset += len(data)

    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(images)))
        for e in entries:
            f.write(e)
        for b in blobs:
            f.write(b)


def main():
    QApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    images = {}
    for size in SIZES:
        img = render(size)
        images[size] = png_bytes(img)
        if size == 256:
            preview = OUT_DIR / "app.png"
            img.save(str(preview))
            print(f"wrote {preview}")

    ico = OUT_DIR / "app.ico"
    pack_ico(images, ico)
    total = sum(len(v) for v in images.values())
    print(f"wrote {ico}  ({len(SIZES)} sizes, {total / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
