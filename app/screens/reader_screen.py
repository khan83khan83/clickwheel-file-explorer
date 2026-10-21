"""Continuous-scroll PDF reader (§5.4).

Wheel scrolls, left click toggles the HUD, right click saves and goes back,
middle click cycles the fit mode. No keyboard.
"""
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen

from app import config, theme
from app.animation import Animator
from app.library.model import LibraryNode
from app.navigation import Screen, ScreenStack
from app.render.pdfrender import renderer, zoom_bucket
from app.widgets.hud import paint_hud

FIT_MODES = ("width", "page", "150", "200")
FIT_LABEL = {"width": "Fit Width", "page": "Fit Page", "150": "150%", "200": "200%"}

SCROLL_PER_STEP = 140       # logical px per wheel detent (§5.4)
HUD_HIDE_MS = 2500
PROGRESS_SAVE_MS = 5000


class ReaderScreen(Screen):
    def __init__(self, stack: ScreenStack, node: LibraryNode):
        super().__init__(stack)
        self.node = node
        self.meta = None
        self.fit_mode = "width"

        self._cw = 0.0
        self._page_tops: list[float] = []
        self._page_hs: list[float] = []
        self._total_h = 0.0

        self.scroll = Animator(0.0)
        self.scroll.tau = 0.060
        self.scroll.epsilon = 0.5
        self.stack.stage.register(self.scroll)

        self.hud = Animator(0.0)
        self.hud.tau = 0.070
        self.hud.epsilon = 0.01
        self.stack.stage.register(self.hud)

        self._hud_timer = QTimer(self)
        self._hud_timer.setSingleShot(True)
        self._hud_timer.setInterval(HUD_HIDE_MS)
        self._hud_timer.timeout.connect(self._hide_hud)

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(PROGRESS_SAVE_MS)
        self._save_timer.timeout.connect(self.save_progress)

        self._last_render_scale = 0.0

    # ------------------------------------------------------------- lifecycle

    @property
    def title(self) -> str:
        return self.node.name

    def _W(self) -> int:
        return self.stack.stage.content_w

    def _H(self) -> int:
        return self.stack.stage.content_h

    def on_enter(self) -> None:
        self.meta = renderer.open(self.node.path)
        self._relayout()
        self._restore_progress()
        renderer.ready.connect(self._on_page_ready)
        self._ensure_pages()
        self._save_timer.start()
        self._show_hud()

    def on_leave(self) -> None:
        self.save_progress()
        self._save_timer.stop()
        self._hud_timer.stop()
        try:
            renderer.ready.disconnect(self._on_page_ready)
        except RuntimeError:
            pass
        renderer.cancel_all()
        renderer.release()          # let go of the file handle, so the user can
        renderer.drop_document(self.node.path)   # delete or move it in Explorer
        self.stack.stage.unregister(self.scroll)
        self.stack.stage.unregister(self.hud)

    def on_scale_changed(self) -> None:
        """Window resized: cached bitmaps are the wrong resolution now (§13.9)."""
        renderer.cancel_all()
        self._ensure_pages()
        self.stack.stage.update()

    # ---------------------------------------------------------------- layout

    def _content_width(self) -> float:
        avail = self._W() - 2 * theme.PAGE_MARGIN_X
        if self.fit_mode == "width":
            return avail
        if self.fit_mode == "page":
            if not self.meta or not self.meta.sizes:
                return avail
            w_pt, h_pt = self.meta.sizes[0]
            return min(avail, self._H() * (w_pt / h_pt))
        return avail * (1.5 if self.fit_mode == "150" else 2.0)

    def _relayout(self, anchor_page: int | None = None) -> None:
        self._cw = self._content_width()
        self._page_tops, self._page_hs = [], []
        y = 0.0
        for (w_pt, h_pt) in (self.meta.sizes if self.meta else []):
            ph = self._cw * (h_pt / w_pt)
            self._page_tops.append(y)
            self._page_hs.append(ph)
            y += ph + theme.PAGE_GAP
        self._total_h = max(0.0, y - theme.PAGE_GAP)

        if anchor_page is not None and self._page_tops:
            i = max(0, min(len(self._page_tops) - 1, anchor_page))
            self.scroll.snap(self._clamp(self._page_tops[i]))

    def _clamp(self, v: float) -> float:
        return max(0.0, min(v, max(0.0, self._total_h - self._H())))

    def _visible_range(self, top: float) -> tuple[int, int]:
        if not self._page_tops:
            return (0, -1)
        first, last = 0, len(self._page_tops) - 1
        for i, t in enumerate(self._page_tops):
            if t + self._page_hs[i] >= top:
                first = i
                break
        for i in range(first, len(self._page_tops)):
            if self._page_tops[i] > top + self._H():
                last = i - 1
                break
            last = i
        return (first, last)

    def current_page(self) -> int:
        """1-based page at the vertical centre of the viewport."""
        if not self._page_tops:
            return 0
        mid = self.scroll.value + self._H() / 2
        for i, t in enumerate(self._page_tops):
            if t <= mid <= t + self._page_hs[i]:
                return i + 1
        return min(len(self._page_tops), max(1, self._visible_range(self.scroll.value)[0] + 1))

    # --------------------------------------------------------------- render

    def _zoom_for(self, page: int) -> float:
        w_pt, _ = self.meta.sizes[page]
        return (self._cw * self.stack.stage.render_scale) / w_pt

    def _ensure_pages(self) -> None:
        """Request the pages around the SETTLED scroll target. Never called from
        paint() — paint does pure cache lookups (§11)."""
        if not self.meta:
            return
        self._last_render_scale = self.stack.stage.render_scale
        first, last = self._visible_range(self.scroll.target_value)
        lo = max(0, first - 1)
        hi = min(len(self._page_tops) - 1, last + 2)
        for i in range(lo, hi + 1):
            renderer.request(self.node.path, i, self._zoom_for(i))

    def _on_page_ready(self, path: str, page: int, zb: float, img) -> None:
        if path == str(self.node.path):
            self.stack.stage.update()

    # ---------------------------------------------------------------- input

    def _show_hud(self) -> None:
        self.hud.target(1.0)
        self._hud_timer.start()
        self.stack.stage._ensure_timer()

    def _hide_hud(self) -> None:
        self.hud.target(0.0)
        self.stack.stage._ensure_timer()
        self.stack.stage.update()

    def on_wheel(self, steps: int) -> None:
        target = self._clamp(self.scroll.target_value + steps * SCROLL_PER_STEP)
        self.scroll.on_done = self._ensure_pages
        self.scroll.target(target)
        self._ensure_pages()
        self._show_hud()
        self.stack.stage._ensure_timer()
        self.stack.stage.update()

    def on_left_click(self, x: float, y: float) -> None:
        if self.hud.target_value > 0.5:
            self._hide_hud()
        else:
            self._show_hud()
            self.stack.stage.update()

    def on_right_click(self, x: float, y: float) -> None:
        self.stack.pop()

    def on_middle_click(self, x: float, y: float) -> None:
        anchor = max(0, self.current_page() - 1)
        i = FIT_MODES.index(self.fit_mode)
        self.fit_mode = FIT_MODES[(i + 1) % len(FIT_MODES)]
        renderer.cancel_all()
        self._relayout(anchor_page=anchor)
        self._ensure_pages()
        self._show_hud()
        self.stack.stage.update()

    # -------------------------------------------------------------- persist

    def save_progress(self) -> None:
        if not self.meta or not self._total_h:
            return
        state = config.load_state()
        key = str(self.node.path.resolve())
        state.setdefault("progress", {})[key] = {
            "page": self.current_page(),
            "scroll_frac": self.scroll.value / self._total_h,
            "total": self.meta.page_count,
            "updated": int(time.time()),
        }
        recent = [p for p in state.get("recent", []) if p != key]
        state["recent"] = ([key] + recent)[:10]
        config.save_state(state)

    def _restore_progress(self) -> None:
        entry = config.load_state().get("progress", {}).get(str(self.node.path.resolve()))
        if entry:
            self.scroll.snap(self._clamp(entry.get("scroll_frac", 0.0) * self._total_h))

    # ----------------------------------------------------------------- paint

    def paint(self, p: QPainter) -> None:
        p.fillRect(0, 0, self._W(), self._H(), theme.color("READER_GUTTER"))

        if not self.meta or not self._page_tops:
            p.setFont(theme.font("F_EMPTY"))
            p.setPen(theme.color("TEXT_DIM"))
            p.drawText(int(self._W() / 2 - 30), int(self._H() / 2), "Opening…")
            return

        top = self.scroll.value
        x = (self._W() - self._cw) / 2.0
        first, last = self._visible_range(top)

        for i in range(first, last + 1):
            dest = QRectF(x, self._page_tops[i] - top, self._cw, self._page_hs[i])
            pm = renderer.peek(self.node.path, i, self._zoom_for(i))
            if pm is not None:
                p.drawPixmap(dest, pm, QRectF(0, 0, pm.width(), pm.height()))
            else:
                p.fillRect(dest, theme.color("PAGE_BG"))
                p.setFont(theme.font("F_COVER_SUB"))
                p.setPen(QColor("#AAAAAA"))
                fm = QFontMetrics(p.font())
                dots = "…"
                p.drawText(int(dest.center().x() - fm.horizontalAdvance(dots) / 2),
                           int(dest.center().y()), dots)

            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(QPen(theme.color("PAGE_BORDER"), 1))
            p.drawRect(dest)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.hud.value > 0.0:
            paint_hud(p, self.current_page(), self.meta.page_count, self.hud.value,
                      self._W(), self._H())

