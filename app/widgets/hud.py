"""Reader HUD overlay. Sized to the content area it is drawn into."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontMetrics, QPainter

from app import theme


def paint_hud(p: QPainter, cur_page: int, total: int, opacity: float,
              W: int, H: int) -> None:
    if opacity <= 0.0:
        return

    prev = p.opacity()
    p.setOpacity(prev * opacity)

    x = theme.HUD_MARGIN
    y = H - theme.HUD_H - theme.HUD_MARGIN
    w = W - 2 * theme.HUD_MARGIN
    h = theme.HUD_H

    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.color("HUD_BG"))
    p.drawRoundedRect(QRectF(x, y, w, h), theme.HUD_RADIUS, theme.HUD_RADIUS)

    p.setFont(theme.font("F_ROW_VALUE"))
    fm = QFontMetrics(p.font())
    p.setPen(theme.color("TEXT"))

    left = f"Page {cur_page} of {total}"
    pct = 0 if total <= 0 else int(round(100.0 * cur_page / total))
    right = f"{pct}%"

    p.drawText(int(x + 14), int(y + 20), left)
    p.drawText(int(x + w - 14 - fm.horizontalAdvance(right)), int(y + 20), right)

    bar_x, bar_w, bar_y = x + 14, w - 28, y + 32
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.color("HUD_BAR_BG"))
    p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, 4), 2, 2)

    frac = 0.0 if total <= 0 else max(0.0, min(1.0, cur_page / total))
    if frac > 0:
        p.setBrush(theme.color("HUD_BAR_FILL"))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w * frac, 4), 2, 2)

    p.setOpacity(prev)
