"""Prototype and verify the virtual click wheel before writing it in Kotlin.

The rotational detent logic and the hit geometry are the parts most likely to
feel wrong, and they are pure maths — so they get worked out and tested here,
where they can actually be run, and the verified constants are carried across.

    python tools/wheel_proto.py          # runs assertions, writes shots/wheel_*.png
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM",
                      "windows" if sys.platform == "win32" else "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt                   # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication                       # noqa: E402

# ----------------------------------------------------------------- geometry
# All in dp. 1 dp = 1/160 inch, so these are real physical sizes: the wheel is
# ~32 mm across, close to a real iPod's 35 mm, which is the size a thumb can
# circle without repositioning the hand.
WHEEL_D = 200.0             # outer diameter
HUB_D = 76.0                # centre button diameter
EDGE_MARGIN = 24.0          # gap from the screen edge when docked
DETENT_DEG = 18.0           # degrees of rotation per selection step
DRAG_SLOP_DP = 8.0          # movement below this is a tap, not a rotation
MENU_ARC_DEG = 70.0         # width of the "back" zone at the top of the ring


def wrap_deg(a: float) -> float:
    """Shortest signed angular difference, in (-180, 180]."""
    return (a + 180.0) % 360.0 - 180.0


class WheelMath:
    """Angular equivalent of the desktop WheelAccumulator.

    Touch angle is accumulated and converted to discrete steps, so a slow drag
    still produces exact single steps and a fast sweep produces several — the
    same contract the mouse wheel has, which keeps both front ends honest.
    """

    def __init__(self, detent_deg: float = DETENT_DEG):
        self.detent = detent_deg
        self._last = None
        self._acc = 0.0
        self.travel = 0.0        # total absolute rotation of this gesture

    def begin(self, angle: float) -> None:
        self._last = angle
        self._acc = 0.0
        self.travel = 0.0

    def move(self, angle: float) -> int:
        """Returns the number of steps crossed since the last call (signed)."""
        if self._last is None:
            self.begin(angle)
            return 0
        d = wrap_deg(angle - self._last)
        self._last = angle
        self._acc += d
        self.travel += abs(d)
        steps = int(self._acc / self.detent)
        if steps:
            self._acc -= steps * self.detent
        return steps

    def end(self) -> None:
        self._last = None
        self._acc = 0.0


def angle_at(cx: float, cy: float, x: float, y: float) -> float:
    """Screen angle in degrees, 0 at 12 o'clock, increasing clockwise."""
    return math.degrees(math.atan2(x - cx, cy - y))


def hit_zone(cx: float, cy: float, x: float, y: float,
             wheel_d: float = WHEEL_D, hub_d: float = HUB_D) -> str:
    """Which part of the wheel a point falls in: hub, menu, ring, or outside."""
    dx, dy = x - cx, y - cy
    dist = math.hypot(dx, dy)
    if dist <= hub_d / 2:
        return "hub"
    if dist > wheel_d / 2:
        return "outside"
    if abs(wrap_deg(angle_at(cx, cy, x, y))) <= MENU_ARC_DEG / 2:
        return "menu"
    return "ring"


def dock_position(w: float, h: float, x: float, y: float,
                  wheel_d: float = WHEEL_D, margin: float = EDGE_MARGIN):
    """Snap a dragged wheel to the nearest screen edge, staying fully on screen.

    Snapping to an edge rather than leaving it anywhere means it never ends up
    stranded mid-screen where no thumb can reach it.
    """
    r = wheel_d / 2
    lo_x, hi_x = margin + r, w - margin - r
    lo_y, hi_y = margin + r, h - margin - r
    x = min(max(x, lo_x), hi_x)
    y = min(max(y, lo_y), hi_y)

    # Distance to each edge; snap along whichever is nearest.
    d = {"left": x - lo_x, "right": hi_x - x, "top": y - lo_y, "bottom": hi_y - y}
    edge = min(d, key=d.get)
    if edge == "left":
        x = lo_x
    elif edge == "right":
        x = hi_x
    elif edge == "top":
        y = lo_y
    else:
        y = hi_y
    return x, y, edge


# ------------------------------------------------------------------- tests

def test_math():
    m = WheelMath()
    m.begin(0.0)
    assert m.move(10.0) == 0, "under one detent must not step"
    assert m.move(20.0) == 1, "crossing a detent yields one step"
    assert m.move(20.0) == 0, "no movement, no step"
    print(f"PASS: one detent = {DETENT_DEG} deg, sub-detent movement is ignored.")

    m.begin(0.0)
    assert m.move(90.0) == 5, "a fast sweep yields several steps at once"
    print("PASS: a 90 deg sweep yields 5 steps.")

    m.begin(0.0)
    assert m.move(-20.0) == -1, "anticlockwise steps backwards"
    print("PASS: direction is signed; anticlockwise goes back.")

    # Crossing the 180 degree seam must not produce a huge jump.
    m.begin(170.0)
    s = m.move(-170.0)
    assert abs(s) <= 2, f"seam crossing produced {s} steps"
    print("PASS: crossing the +/-180 seam behaves like a small move.")

    # Residue carries, so a slow continuous drag never loses a step.
    m.begin(0.0)
    total, a = 0, 0.0
    for _ in range(360):
        a += 1.0
        total += m.move(a)
    assert total == int(360 / DETENT_DEG), f"a full turn gave {total} steps"
    print(f"PASS: one full rotation = {total} steps, no drift over 360 samples.")


def test_zones():
    cx = cy = 100.0
    assert hit_zone(cx, cy, cx, cy) == "hub"
    assert hit_zone(cx, cy, cx, cy - WHEEL_D / 2 + 10) == "menu", "top of ring is back"
    assert hit_zone(cx, cy, cx + WHEEL_D / 2 - 10, cy) == "ring"
    assert hit_zone(cx, cy, cx, cy + WHEEL_D / 2 - 10) == "ring"
    assert hit_zone(cx, cy, cx + WHEEL_D, cy) == "outside"
    print("PASS: hub / menu / ring / outside zones resolve correctly.")


def test_docking():
    W, H = 1280.0, 800.0
    x, y, edge = dock_position(W, H, 1200.0, 700.0)
    assert edge in ("right", "bottom")
    assert x + WHEEL_D / 2 <= W and y + WHEEL_D / 2 <= H, "wheel left the screen"

    # Dragged off-screen entirely, it must come back.
    x, y, edge = dock_position(W, H, -500.0, 5000.0)
    assert EDGE_MARGIN <= x <= W - EDGE_MARGIN
    assert EDGE_MARGIN <= y <= H - EDGE_MARGIN
    print(f"PASS: docking clamps on screen and snaps to an edge ({edge}).")


# ------------------------------------------------------------------ mockup

def draw_wheel(p: QPainter, cx: float, cy: float, dark: bool, pressed=None):
    r = WHEEL_D / 2
    hub_r = HUB_D / 2

    fg = QColor("#EDEDED") if dark else QColor("#1B1B1B")
    ring_a = QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 16)
    ring_b = QColor(0, 0, 0, 90) if dark else QColor(0, 0, 0, 26)

    # Soft shadow so the wheel reads as floating above the content.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 70 if dark else 40))
    p.drawEllipse(QPointF(cx, cy + 4), r + 2, r + 2)

    ring = QRadialGradient(cx, cy - r * 0.3, r * 1.4)
    if dark:
        ring.setColorAt(0.0, QColor(64, 64, 66, 235))
        ring.setColorAt(1.0, QColor(30, 30, 32, 235))
    else:
        ring.setColorAt(0.0, QColor(252, 252, 252, 238))
        ring.setColorAt(1.0, QColor(222, 222, 226, 238))
    p.setBrush(ring)
    p.drawEllipse(QPointF(cx, cy), r, r)

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ring_a, 1.5))
    p.drawEllipse(QPointF(cx, cy), r - 1, r - 1)

    # Pressed-zone highlight
    if pressed == "menu":
        path = QPainterPath()
        path.moveTo(cx, cy)
        path.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r),
                   90 - MENU_ARC_DEG / 2, MENU_ARC_DEG)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30) if dark else QColor(0, 0, 0, 20))
        p.drawPath(path)

    # Hub
    hub = QLinearGradient(cx, cy - hub_r, cx, cy + hub_r)
    if dark:
        hub.setColorAt(0.0, QColor(78, 78, 82))
        hub.setColorAt(1.0, QColor(44, 44, 48))
    else:
        hub.setColorAt(0.0, QColor(255, 255, 255))
        hub.setColorAt(1.0, QColor(232, 232, 236))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(hub)
    p.drawEllipse(QPointF(cx, cy), hub_r, hub_r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ring_b, 1.2))
    p.drawEllipse(QPointF(cx, cy), hub_r, hub_r)

    # Labels: MENU at the top, subtle chevrons left/right for feel.
    f = QFont("Segoe UI", 0)
    f.setPixelSize(13)
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    p.setPen(QColor(fg.red(), fg.green(), fg.blue(), 190))
    p.drawText(QRectF(cx - 60, cy - r + 12, 120, 20),
               Qt.AlignmentFlag.AlignCenter, "MENU")

    p.setPen(QPen(QColor(fg.red(), fg.green(), fg.blue(), 120), 2.0,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    for sgn in (-1, 1):
        bx = cx + sgn * (r - 26)
        p.drawLine(QPointF(bx - sgn * 4, cy - 6), QPointF(bx + sgn * 4, cy))
        p.drawLine(QPointF(bx + sgn * 4, cy), QPointF(bx - sgn * 4, cy + 6))


def mock(dark: bool, name: str, portrait: bool):
    # Xiaomi Pad 8 is an 11-inch class tablet; in dp that is about 1280x800
    # landscape. Rendered 1.5x here purely so the PNG is legible.
    W, H = (800, 1280) if portrait else (1280, 800)
    S = 1.5
    img = QImage(int(W * S), int(H * S), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(S, S)

    bg = QColor("#191919") if dark else QColor("#FAFAFA")
    surface = QColor("#202020") if dark else QColor("#FFFFFF")
    text = QColor("#EDEDED") if dark else QColor("#1B1B1B")
    dim = QColor("#8C8C8C") if dark else QColor("#6B6B6B")
    accent = QColor("#4C8DFF") if dark else QColor("#0A66E0")
    p.fillRect(0, 0, W, H, bg)

    # Title strip
    f = QFont("Segoe UI", 0); f.setPixelSize(15); f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f); p.setPen(text)
    p.drawText(QRectF(24, 0, 400, 56), Qt.AlignmentFlag.AlignVCenter, "KHAN83")

    # List
    list_w = W * (1.0 if portrait else 0.38)
    rows = ["Covers (5)", "DJI 001", "EXE program", "Movies", "Outplayed",
            "Random", "READ", "Real Analysis", "Sheet Music", "Speech"]
    row_h = 52
    for i, label in enumerate(rows):
        y = 64 + i * row_h
        if y + row_h > H - 40:
            break
        if i == 1:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(accent)
            p.drawRoundedRect(QRectF(12, y + 3, list_w - 24, row_h - 6), 12, 12)
            p.setPen(QColor("#FFFFFF"))
        else:
            p.setPen(text)
        f.setPixelSize(16); f.setWeight(QFont.Weight.Normal); p.setFont(f)
        p.drawText(QRectF(28, y, list_w - 60, row_h),
                   Qt.AlignmentFlag.AlignVCenter, label)

    if not portrait:
        p.fillRect(QRectF(list_w, 56, W - list_w, H - 56), surface)
        f.setPixelSize(14); p.setFont(f); p.setPen(dim)
        p.drawText(QRectF(list_w, H - 90, W - list_w, 30),
                   Qt.AlignmentFlag.AlignCenter, "preview")

    # The wheel, docked bottom-right within thumb reach.
    cx = W - EDGE_MARGIN - WHEEL_D / 2
    cy = H - EDGE_MARGIN - WHEEL_D / 2
    draw_wheel(p, cx, cy, dark, pressed="menu" if dark else None)

    # Thumb-reach arc from the bottom-right corner, ~140 mm.
    p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 70), 2,
                  Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    reach = 140 / 25.4 * 160        # mm -> dp
    p.drawArc(QRectF(W - reach, H - reach, reach * 2, reach * 2), 90 * 16, 90 * 16)
    f.setPixelSize(12); p.setFont(f)
    p.setPen(QColor(accent.red(), accent.green(), accent.blue(), 160))
    p.drawText(QRectF(W - 300, H - reach - 26, 280, 20),
               Qt.AlignmentFlag.AlignRight, "one-handed thumb reach (~140 mm)")

    p.end()
    out = ROOT / "shots" / f"{name}.png"
    out.parent.mkdir(exist_ok=True)
    img.save(str(out))
    print(f"wrote {out}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_math()
    test_zones()
    test_docking()
    mock(dark=True, name="wheel_landscape_dark", portrait=False)
    mock(dark=False, name="wheel_portrait_light", portrait=True)
