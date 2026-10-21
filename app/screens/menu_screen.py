"""Browsing list with a preview panel, reflowing to the window size."""
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFontMetrics, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)

from app import shell, theme
from app.animation import Animator
from app.input import advance
from app.library.covers import cache as cover_cache
from app.library.model import LibraryNode
from app.navigation import Screen, ScreenStack

ART_REQ_W = theme.COVER_REQ_W


def mosaic_rects(aspects: List[float], box_w: float, box_h: float,
                 gap: float) -> List[QRectF]:
    """Lay previews out undistorted, the way a photo library does.

    Every way of splitting the items into consecutive rows is tried. Within a
    row all items share one height and together fill the width at their own
    aspect ratios (w/h); the whole block is then scaled to fit the box. The
    split showing the most picture wins, discounted when tile sizes are very
    uneven (one huge hero over three thumbnails reads as lopsided) — so
    landscape video frames stack, portrait covers sit side by side, and
    nothing is stretched or cropped.
    Rects are relative to the box's top-left, centred in it.
    """
    n = len(aspects)
    if n == 0 or box_w <= 0 or box_h <= 0:
        return []

    best, best_score = [], -1.0
    for mask in range(1 << (n - 1)):            # bit i set: break after item i
        rows, row = [], [0]
        for i in range(1, n):
            if mask & (1 << (i - 1)):
                rows.append(row)
                row = []
            row.append(i)
        rows.append(row)

        # Full-width row heights, then one scale factor for the whole block.
        heights = [(box_w - gap * (len(r) - 1)) / sum(aspects[i] for i in r)
                   for r in rows]
        v_gaps = gap * (len(rows) - 1)
        if sum(heights) <= 0 or box_h <= v_gaps:
            continue
        s = min(1.0, (box_h - v_gaps) / sum(heights))

        rects, y = [], 0.0
        for r, h in zip(rows, heights):
            h *= s
            row_w = sum(aspects[i] * h for i in r) + gap * (len(r) - 1)
            x = (box_w - row_w) / 2
            for i in r:
                w = aspects[i] * h
                rects.append((i, QRectF(x, y, w, h)))
                x += w + gap
            y += h + gap
        dy = (box_h - (y - gap)) / 2
        areas = [rc.width() * rc.height() for _i, rc in rects]
        score = sum(areas) * (min(areas) / max(areas)) ** 0.5
        if score > best_score:
            best_score = score
            best = [rc.translated(0, dy) for _i, rc in sorted(rects, key=lambda t: t[0])]
    return best


def has_pdfs(n: LibraryNode) -> bool:
    if not n.is_dir:
        return True
    return bool(n.docs) or any(has_pdfs(child) for child in n.children)


@dataclass
class MenuRow:
    label: str
    kind: str                       # folder | covers | doc | action | value
    node: Optional[LibraryNode]
    value: Optional[str] = None
    action: Optional[str] = None


class MenuScreen(Screen):
    def __init__(self, stack: ScreenStack, title: str, rows: List[MenuRow],
                 node: Optional[LibraryNode] = None):
        super().__init__(stack)
        self._title = title
        self.rows = rows
        self.node = node
        self.sel = 0
        self.top = 0

        self.scroll_anim = Animator(0.0)
        self.scroll_anim.tau = theme.MENU_SCROLL_TAU
        self.scroll_anim.epsilon = 0.004
        self.stack.stage.register(self.scroll_anim)

        self.art_anim = Animator(0.0)
        self.art_anim.tau = 0.09
        self.art_anim.epsilon = 0.01
        self.stack.stage.register(self.art_anim)

        self.art_timer = QTimer(self)
        self.art_timer.setSingleShot(True)
        self.art_timer.setInterval(120)
        self.art_timer.timeout.connect(self._fetch_art)

        cover_cache.ready.connect(self._on_cover_ready)

        self.art_pmaps = []
        self._current_art_keys = []
        self._current_docs = []

    # ------------------------------------------------------------ geometry

    @property
    def title(self) -> str:
        return self._title

    @property
    def library_path(self):
        return self.node.path if self.node else None

    def _W(self) -> int:
        return self.stack.stage.content_w

    def _H(self) -> int:
        return self.stack.stage.content_h

    def visible_rows(self) -> int:
        return max(1, int(self._H() // theme.ROW_H))

    def show_art(self) -> bool:
        """Whether the window is wide enough to earn a preview panel."""
        return self._W() >= theme.ART_MIN_W

    def list_width(self) -> int:
        return theme.list_width(self._W()) if self.show_art() else self._W()

    def on_scale_changed(self) -> None:
        # Crossing the breakpoint either reveals a panel that has no art yet, or
        # hides one; re-run the fetch so the new layout is populated.
        self.art_timer.start()

    # ----------------------------------------------------------- lifecycle

    def on_enter(self) -> None:
        self.scroll_anim.snap(float(self.top))
        self.art_timer.start()

    def on_leave(self) -> None:
        self.art_timer.stop()
        try:
            cover_cache.ready.disconnect(self._on_cover_ready)
        except RuntimeError:
            pass
        self.stack.stage.unregister(self.scroll_anim)
        self.stack.stage.unregister(self.art_anim)

    # ----------------------------------------------------------------- art

    def _first_docs(self, node: LibraryNode, limit=4) -> list:
        """Up to `limit` files to preview for this row.

        For a folder that has not been listed yet, read it one level deep — the
        cost of one os.scandir, and only after the 120 ms selection debounce.
        Never recurses: under the Desktop that could be thousands of entries.
        """
        if not node.is_dir:
            return [node]
        if node.docs or node.children:
            return list(node.docs[:limit])
        from app.library.scanner import list_dir
        try:
            return list(list_dir(node.path).docs[:limit])
        except OSError:
            return []

    def _fetch_art(self) -> None:
        if not self.rows or not self.show_art():
            return          # narrow layout: no panel, so no covers to render
        row = self.rows[self.sel]

        docs = []
        if row.kind == "doc" and row.node:
            docs = [row.node]
        elif row.kind in ("folder", "covers") and row.node:
            docs = self._first_docs(row.node)

        self.art_anim.snap(0.0)
        self.art_pmaps = [None] * len(docs)
        self._current_docs = docs
        self._current_art_keys = [f"{d.cache_key}_{ART_REQ_W}" for d in docs]

        for i, d in enumerate(docs):
            pm = cover_cache.request(d, ART_REQ_W)
            if pm:
                self.art_pmaps[i] = pm

        if docs:
            self.art_anim.target(1.0)
            self.stack.stage._ensure_timer()
            self.stack.stage.update()

    def _on_cover_ready(self, key: str, img: QImage) -> None:
        if key not in self._current_art_keys:
            return
        idx = self._current_art_keys.index(key)
        doc = self._current_docs[idx]
        pm = cover_cache.request(doc, ART_REQ_W) if not img.isNull() \
            else cover_cache.placeholder(doc)
        if pm:
            self.art_pmaps[idx] = pm
            self.stack.stage.update()

    # --------------------------------------------------------------- input

    def on_wheel(self, steps: int) -> None:
        if not self.rows:
            return
        old = self.sel
        self.sel, wrapped = advance(self.sel, steps, len(self.rows))
        if self.sel == old:
            return

        vis = self.visible_rows()
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + vis:
            self.top = self.sel - vis + 1
        self.top = max(0, min(self.top, max(0, len(self.rows) - vis)))

        if wrapped:
            # Start short of the destination, on the side the motion came from,
            # and slide in. Sliding the whole length of the list would be a slow
            # blur; snapping outright would be invisible.
            direction = 1.0 if steps > 0 else -1.0
            self.scroll_anim.snap(float(self.top)
                                  - direction * theme.WRAP_SLIDE_ROWS)
            self.scroll_anim.tau = theme.WRAP_TAU
            self.scroll_anim.on_done = self._restore_scroll_tau
            self.scroll_anim.target(float(self.top))
        else:
            self.scroll_anim.tau = theme.MENU_SCROLL_TAU
            self.scroll_anim.target(float(self.top))

        self.art_timer.start()
        self.stack.stage._ensure_timer()
        self.stack.stage.update()

    def _restore_scroll_tau(self) -> None:
        self.scroll_anim.tau = theme.MENU_SCROLL_TAU

    def on_left_click(self, x: float, y: float) -> None:
        if not self.rows:
            return
        row = self.rows[self.sel]

        if row.kind == "folder" and row.node:
            # from_path, not from_node: listing is lazy, so the node held by a
            # row is a stub with empty children and docs. Building a screen
            # straight from it produces an empty folder.
            child = MenuScreen.from_path(self.stack, row.node.path, self.node)
            if child:
                self.stack.push(child)

        elif row.kind == "covers" and row.node and row.node.docs:
            from app.screens.coverflow_screen import CoverFlowScreen
            self.stack.push(CoverFlowScreen(self.stack, row.node.docs))

        elif row.kind == "doc" and row.node:
            shell.open_file(row.node.path)

        elif row.kind == "action":
            if row.action == "exit":
                sys.exit(0)
            elif row.action == "theme":
                theme.set_mode("light" if theme.is_dark() else "dark")
                self.stack.stage.update()
            elif row.action == "library":
                self._choose_library_folder()
            elif row.action == "refresh":
                if self.stack.library:
                    self.stack.library.refresh()
            else:
                print(f"Action: {row.action}")

    def on_middle_click(self, x: float, y: float) -> None:
        """Show the highlighted item in Explorer — the app never writes to the
        library itself, so this is how you manage it."""
        if not self.rows:
            return
        row = self.rows[self.sel]
        target = row.node.path if row.node else None
        if target is None and self.node:
            target = self.node.path
        if target:
            shell.reveal(target)

    def _choose_library_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from app import config
        start = str(config.get("library_root") or "")
        chosen = QFileDialog.getExistingDirectory(
            None, "Choose the folder to browse", start)
        if not chosen:
            return
        config.set_value("library_root", str(Path(chosen).resolve()))
        if self.stack.library:
            self.stack.library.set_root(Path(chosen))

    # --------------------------------------------------------------- paint

    def paint(self, p: QPainter) -> None:
        W, H = self._W(), self._H()
        lw = self.list_width()

        p.fillRect(0, 0, W, H, self.stack.stage.background_color())

        if self.show_art():
            self._paint_art(p, lw, W - lw, H)
            p.setPen(QPen(theme.color("BORDER"), 1))
            p.drawLine(lw, 0, lw, H)

        if not self.rows:
            p.setFont(theme.font("F_EMPTY"))
            p.setPen(theme.color("TEXT_DIM"))
            fm = QFontMetrics(p.font())
            t = "No PDFs here"
            p.drawText(int(lw / 2 - fm.horizontalAdvance(t) / 2), int(H / 2), t)
            return

        p.save()
        p.setClipRect(0, 0, lw, H)

        vis = self.visible_rows()
        first = max(0, int(self.scroll_anim.value))
        last = min(len(self.rows) - 1, first + vis + 1)

        for i in range(first, last + 1):
            self._paint_row(p, i, lw)

        p.restore()
        self._paint_scrollbar(p, lw, H, vis)

    def _paint_row(self, p: QPainter, i: int, lw: int) -> None:
        row = self.rows[i]
        ry = round((i - self.scroll_anim.value) * theme.ROW_H)
        selected = (i == self.sel)

        if selected:
            r = QRectF(6, ry + 2, lw - 12, theme.ROW_H - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("SEL_BG"))
            p.drawRoundedRect(r, theme.ROW_RADIUS, theme.ROW_RADIUS)
            fg = theme.color("SEL_TEXT")
            p.setFont(theme.font("F_ROW_SEL"))
        else:
            fg = theme.color("TEXT")
            p.setFont(theme.font("F_ROW"))

        fm = QFontMetrics(p.font())
        val_w = 0
        if row.kind == "value" and row.value:
            val_w = QFontMetrics(theme.font("F_ROW_VALUE")).horizontalAdvance(row.value) + 12

        avail = lw - theme.ROW_PAD_L - theme.ROW_PAD_R - val_w
        label = fm.elidedText(row.label, Qt.TextElideMode.ElideRight, max(10, avail))

        p.setPen(fg)
        baseline = ry + theme.ROW_H / 2 + fm.capHeight() / 2
        p.drawText(theme.ROW_PAD_L, int(baseline), label)

        if row.kind in ("folder", "covers"):
            p.setPen(QPen(theme.color("CHEVRON_SEL" if selected else "CHEVRON"), 1.5,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            cx = lw - theme.CHEVRON_INSET
            cy = ry + theme.ROW_H / 2
            p.drawLine(QPointF(cx - 2, cy - 4), QPointF(cx + 2, cy))
            p.drawLine(QPointF(cx + 2, cy), QPointF(cx - 2, cy + 4))

        if row.kind == "value" and row.value:
            p.setFont(theme.font("F_ROW_VALUE"))
            p.setPen(theme.color("SEL_TEXT") if selected else theme.color("TEXT_DIM"))
            vfm = QFontMetrics(p.font())
            p.drawText(lw - theme.ROW_PAD_L - vfm.horizontalAdvance(row.value),
                       int(baseline), row.value)

    def _paint_scrollbar(self, p: QPainter, lw: int, H: int, vis: int) -> None:
        n = len(self.rows)
        if n <= vis:
            return
        track_h = H - 2 * theme.SCROLLBAR_INSET
        thumb_h = max(28.0, track_h * vis / n)
        frac = self.scroll_anim.value / max(1, n - vis)
        y = theme.SCROLLBAR_INSET + (track_h - thumb_h) * min(1.0, max(0.0, frac))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("SCROLL_THUMB"))
        p.drawRoundedRect(QRectF(lw - theme.SCROLLBAR_W - 3, y,
                                 theme.SCROLLBAR_W, thumb_h), 2, 2)

    # ----------------------------------------------------------- art panel

    def _paint_art(self, p: QPainter, x: int, w: int, h: int) -> None:
        if w <= 40:
            return
        g = QLinearGradient(x, 0, x, h)
        g.setColorAt(0.0, theme.color("SURFACE"))
        g.setColorAt(1.0, theme.color("SURFACE_ALT"))
        p.fillRect(QRectF(x, 0, w, h), g)

        pmaps = [pm for pm in self.art_pmaps if pm is not None and not pm.isNull()]
        label_h = theme.ART_LABEL_H
        box_w = w - 2 * theme.ART_PAD
        box_h = h - 2 * theme.ART_PAD - label_h
        if box_w < 30 or box_h < 30:
            return

        p.save()
        p.setOpacity(self.art_anim.value)

        if not pmaps:
            p.setOpacity(1.0)
            p.setFont(theme.font("F_EMPTY"))
            p.setPen(theme.color("TEXT_FAINT"))
            fm = QFontMetrics(p.font())
            t = "…"
            p.drawText(int(x + w / 2 - fm.horizontalAdvance(t) / 2), int(h / 2), t)
            p.restore()
            return

        cx = x + w / 2
        if len(pmaps) == 1:
            self._draw_cover(p, pmaps[0], cx, theme.ART_PAD, box_w, box_h)
        else:
            pmaps = pmaps[:4]
            rects = mosaic_rects([pm.width() / pm.height() for pm in pmaps],
                                 box_w, box_h, gap=10)
            for pm, r in zip(pmaps, rects):
                self._draw_cover_rect(p, pm, r.translated(x + theme.ART_PAD,
                                                          theme.ART_PAD))

        p.setOpacity(1.0)
        row = self.rows[self.sel] if self.rows else None
        if row:
            p.setFont(theme.font("F_ART_TITLE"))
            fm = QFontMetrics(p.font())
            p.setPen(theme.color("TEXT"))
            t = fm.elidedText(row.label, Qt.TextElideMode.ElideRight, w - 2 * theme.ART_PAD)
            p.drawText(int(cx - fm.horizontalAdvance(t) / 2), int(h - theme.ART_PAD - 24), t)

            sub = ""
            if row.kind == "covers" and row.node:
                sub = f"{len(row.node.docs)} files"
            elif row.node and row.node.is_dir:
                sub = "Folder"          # a deep count would mean walking it
            elif row.node:
                mb = row.node.size / (1024 * 1024)
                sub = (f"{row.node.size / 1024:.0f} KB" if mb < 1
                       else f"{mb:.1f} MB")
            if sub:
                p.setFont(theme.font("F_ART_SUB"))
                sfm = QFontMetrics(p.font())
                p.setPen(theme.color("TEXT_DIM"))
                p.drawText(int(cx - sfm.horizontalAdvance(sub) / 2),
                           int(h - theme.ART_PAD - 6), sub)
        p.restore()

    def _draw_cover(self, p, pm, cx, top, box_w, box_h) -> None:
        s = min(box_w / pm.width(), box_h / pm.height())
        cw, ch = pm.width() * s, pm.height() * s
        self._draw_cover_rect(p, pm, QRectF(cx - cw / 2, top + (box_h - ch) / 2, cw, ch))

    def _draw_cover_rect(self, p: QPainter, pm: QPixmap, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("SHADOW"))
        p.drawRoundedRect(r.adjusted(2, 4, 2, 5), theme.CARD_RADIUS, theme.CARD_RADIUS)

        path = QPainterPath()
        path.addRoundedRect(r, theme.CARD_RADIUS, theme.CARD_RADIUS)
        p.save()
        p.setClipPath(path)
        p.drawPixmap(r, pm, QRectF(0, 0, pm.width(), pm.height()))
        p.restore()

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.color("CARD_EDGE"), 1))
        p.drawRoundedRect(r, theme.CARD_RADIUS, theme.CARD_RADIUS)

    # ------------------------------------------------------------ building

    @classmethod
    def from_path(cls, stack: ScreenStack, path, parent=None) -> "MenuScreen":
        """List a directory: folders first, then files — Explorer's order."""
        from app.library.scanner import list_dir
        node = list_dir(Path(path), parent)
        return cls.from_node(stack, node)

    @classmethod
    def from_node(cls, stack: ScreenStack, node: LibraryNode) -> Optional["MenuScreen"]:
        if not node.is_dir:
            return None

        rows = []
        # Offered even for a single file: in a narrow window the preview panel
        # is suppressed, so this is the only route to seeing a cover at all.
        if node.docs:
            rows.append(MenuRow(f"Covers ({len(node.docs)})", "covers", node))
        for folder in node.children:
            rows.append(MenuRow(folder.name, "folder", folder))
        for doc in node.docs:
            rows.append(MenuRow(doc.name, "doc", doc))
        return MenuScreen(stack, node.name, rows, node=node)
