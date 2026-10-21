"""Cover Flow, sized from the window rather than a fixed canvas."""
from typing import List

from PySide6.QtCore import (QObject, QPointF, QRectF, QRunnable, Qt,
                            QThreadPool, Signal)
from PySide6.QtGui import (QColor, QFontMetrics, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)

from app import shell, theme
from app.animation import Animator
from app.input import advance
from app.library.covers import cache as cover_cache
from app.library.document import Doc
from app.library.model import LibraryNode
from app.navigation import Screen, ScreenStack
from app.render.reflection import make_reflection
from app.render.transforms import perspective_y

COVER_W = theme.COVER_REQ_W

_page_count_pool = QThreadPool()
_page_count_pool.setMaxThreadCount(2)


def sign(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


class PageCountSignals(QObject):
    ready = Signal(str, int)


class PageCountWorker(QRunnable):
    def __init__(self, node: LibraryNode, signals: PageCountSignals):
        super().__init__()
        self.node = node
        self.signals = signals

    def run(self):
        doc = None
        try:
            doc = Doc(self.node.path)
            self.signals.ready.emit(str(self.node.path), doc.page_count())
        except Exception:
            self.signals.ready.emit(str(self.node.path), -1)
        finally:
            if doc:
                doc.close()


class CoverFlowScreen(Screen):
    def __init__(self, stack: ScreenStack, docs: List[LibraryNode], start_index: int = 0):
        super().__init__(stack)
        self.docs = docs
        self.index = max(0, min(len(docs) - 1, start_index)) if docs else 0

        self.pos_anim = Animator(float(self.index))
        self.pos_anim.tau = theme.CF_POS_TAU
        self.pos_anim.epsilon = 0.002
        self.stack.stage.register(self.pos_anim)

        self._pmaps = {}
        self._refls = {}
        self._pc_signals = PageCountSignals()
        self._pc_signals.ready.connect(self._on_page_count)
        self._fetching_pc = set()

    # ------------------------------------------------------------ geometry

    @property
    def title(self) -> str:
        if self.docs and self.docs[self.index].parent:
            return self.docs[self.index].parent.name
        return "Covers"

    @property
    def library_path(self):
        parent = self.docs[0].parent if self.docs else None
        return parent.path if parent else None

    def on_middle_click(self, x: float, y: float) -> None:
        if self.docs:
            shell.reveal(self.docs[self.index].path)

    def _cover_box(self):
        """Cover size derived from the window: tall enough to dominate, with
        room for the label block underneath."""
        W, H = self.stack.stage.content_w, self.stack.stage.content_h
        h = max(120.0, min(H * theme.CF_HEIGHT_FRAC, H - theme.CF_HEIGHT_RESERVE))
        w = h / 1.3
        if w > W * theme.CF_WIDTH_CAP:
            w = W * theme.CF_WIDTH_CAP
            h = w * 1.3
        return w, h

    # ----------------------------------------------------------- lifecycle

    def on_enter(self) -> None:
        self.pos_anim.snap(float(self.index))
        cover_cache.ready.connect(self._on_cover_ready)
        self._ensure_covers()
        self._check_settled()

    def on_leave(self) -> None:
        try:
            cover_cache.ready.disconnect(self._on_cover_ready)
        except RuntimeError:
            pass
        self.stack.stage.unregister(self.pos_anim)

    # -------------------------------------------------------------- covers

    def _install_placeholder(self, doc: LibraryNode) -> None:
        if doc.cache_key in self._pmaps:
            return
        pm = cover_cache.placeholder(doc)
        self._pmaps[doc.cache_key] = pm
        self._refls[doc.cache_key] = make_reflection(pm)

    def _ensure_covers(self) -> None:
        """Acquire pixmaps and reflections near the centre. Called from enter,
        wheel and cover-arrival — never from paint()."""
        if not self.docs:
            return
        lo = max(0, self.index - theme.CF_RANGE - 1)
        hi = min(len(self.docs) - 1, self.index + theme.CF_RANGE + 1)
        for i in range(lo, hi + 1):
            doc = self.docs[i]
            if doc.cache_key in self._pmaps:
                continue
            pm = cover_cache.request(doc, COVER_W)
            if pm:
                self._pmaps[doc.cache_key] = pm
                self._refls[doc.cache_key] = make_reflection(pm)
            else:
                self._install_placeholder(doc)

    def _on_cover_ready(self, key: str, img: QImage) -> None:
        if not key.endswith(f"_{COVER_W}"):
            return
        doc_key = key.rsplit("_", 1)[0]
        if not img.isNull():
            pm = QPixmap.fromImage(img)
            self._pmaps[doc_key] = pm
            self._refls[doc_key] = make_reflection(pm)
        self.stack.stage.update()

    def _on_page_count(self, path: str, count: int) -> None:
        self._fetching_pc.discard(path)
        for d in self.docs:
            if str(d.path) == path:
                d.pages = count if count >= 0 else None
                self.stack.stage.update()
                break

    def _check_settled(self):
        if self.pos_anim.active or not self.docs:
            return
        doc = self.docs[self.index]
        if doc.path.suffix.lower() != ".pdf":
            return                      # only PDFs have a page count
        if doc.pages is None and str(doc.path) not in self._fetching_pc:
            self._fetching_pc.add(str(doc.path))
            _page_count_pool.start(PageCountWorker(doc, self._pc_signals))

    # --------------------------------------------------------------- input

    def on_wheel(self, steps: int) -> None:
        if not self.docs:
            return
        # No wrapping here: the fan shows the covers either side of the centre,
        # so looping round would contradict what is on screen. It stops at the
        # ends. The list still wraps.
        self.index, _ = advance(self.index, steps, len(self.docs), wrap=False)
        self._ensure_covers()
        self.pos_anim.on_done = self._check_settled
        self.pos_anim.target(float(self.index))
        self.stack.stage._ensure_timer()
        self.stack.stage.update()

    def on_left_click(self, x: float, y: float) -> None:
        # Always the CENTRE cover, wherever the click landed.
        if self.docs:
            shell.open_file(self.docs[self.index].path)

    def on_right_click(self, x: float, y: float) -> None:
        self.stack.pop()

    # --------------------------------------------------------------- paint

    def paint(self, p: QPainter) -> None:
        W, H = self.stack.stage.content_w, self.stack.stage.content_h

        bg = QRadialGradient(W / 2, H * 0.42, max(W, H) * 0.75)
        bg.setColorAt(0.0, theme.color("CF_BG"))
        bg.setColorAt(1.0, theme.color("CF_BG_EDGE"))
        p.fillRect(QRectF(0, 0, W, H), bg)

        if not self.docs:
            return

        cw, ch = self._cover_box()
        cy = H * theme.CF_CENTRE_Y_FRAC
        gap = cw * theme.CF_GAP_FRAC
        step = cw * theme.CF_STEP_FRAC
        pos = self.pos_anim.value

        drawn = []
        for i, doc in enumerate(self.docs):
            off = i - pos
            a = abs(off)
            if a > theme.CF_RANGE + 1:
                continue
            if a <= 1.0:
                x = W / 2 + off * gap
                angle = theme.CF_ANGLE * a * sign(off)
                scale = 1.0 - (1.0 - theme.CF_SIDE_SCALE) * a
            else:
                x = W / 2 + sign(off) * (gap + (a - 1.0) * step)
                angle = theme.CF_ANGLE * sign(off)
                scale = theme.CF_SIDE_SCALE
            drawn.append((1000 - a * 10, i, doc, x, angle, scale, a))

        drawn.sort(key=lambda it: it[0])
        self._drawn_indices = [it[1] for it in drawn]
        self._last_drawn = drawn

        # Keep the fan out of the label band at the bottom.
        p.save()
        p.setClipRect(QRectF(0, 0, W, max(0, H - theme.CF_LABEL_BAND)))

        for _z, _i, doc, x, angle, scale, a in drawn:
            pm = self._pmaps.get(doc.cache_key)
            if pm is None:
                continue
            refl = self._refls.get(doc.cache_key, QPixmap())

            s = min(cw / pm.width(), ch / pm.height())
            w, h = pm.width() * s, pm.height() * s

            p.save()
            p.translate(x, cy)
            p.scale(scale, scale)
            # Perspective distance must scale with the cover, or a large cover
            # pushes x/d far enough to stretch the near edge grotesquely.
            p.setTransform(perspective_y(angle, w * theme.CF_PERSP_RATIO), True)

            rect = QRectF(-w / 2, -h / 2, w, h)
            path = QPainterPath()
            path.addRoundedRect(rect, theme.CARD_RADIUS, theme.CARD_RADIUS)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(rect, pm, QRectF(0, 0, pm.width(), pm.height()))
            p.restore()

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(theme.color("CARD_EDGE"), 1))
            p.drawRoundedRect(rect, theme.CARD_RADIUS, theme.CARD_RADIUS)

            refl_h = h * theme.REFLECT_FRAC
            if not refl.isNull():
                p.drawPixmap(QRectF(-w / 2, h / 2, w, refl_h), refl,
                             QRectF(0, 0, refl.width(), refl.height()))

            if a > 0:
                # Recede toward the backdrop, not toward black — blackening a
                # cover on a light background just makes it look dirty.
                dim = QColor(theme.color("CF_BG_EDGE"))
                dim.setAlpha(int(150 * min(a, 1.5) / 1.5))
                p.fillRect(rect, dim)
                if not refl.isNull():
                    p.fillRect(QRectF(-w / 2, h / 2, w, refl_h), dim)
            p.restore()

        p.restore()                 # release the label-band clip
        self._paint_labels(p, W, H, pos)

    def _paint_labels(self, p: QPainter, W: int, H: int, pos: float) -> None:
        doc = self.docs[self.index]
        opacity = max(0.0, min(1.0, 1.0 - abs(pos - self.index) * 1.5))
        self._title_opacity = opacity
        if opacity <= 0:
            return

        p.setOpacity(opacity)
        p.setFont(theme.font("F_COVER_TITLE"))
        fm = QFontMetrics(p.font())
        p.setPen(theme.color("TEXT"))
        t = fm.elidedText(doc.name, Qt.TextElideMode.ElideRight, int(W * 0.8))
        p.drawText(int(W / 2 - fm.horizontalAdvance(t) / 2), int(H - 42), t)

        p.setFont(theme.font("F_COVER_SUB"))
        sfm = QFontMetrics(p.font())
        p.setPen(theme.color("TEXT_DIM"))
        mb = doc.size / (1024 * 1024)
        size = f"{doc.size / 1024:.0f} KB" if mb < 1 else f"{mb:.1f} MB"
        sub = f"{doc.pages} pages · {size}" if doc.pages else size
        p.drawText(int(W / 2 - sfm.horizontalAdvance(sub) / 2), int(H - 18), sub)
        p.setOpacity(1.0)
