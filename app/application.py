"""The application window.

An ordinary native window: Windows draws the title bar, handles dragging,
snapping, PowerToys zones and the taskbar button. Reimplementing any of that
was a mistake — the custom drag in particular could latch on and move the
window on hover.

Only the docked side panel is frameless, where a title bar would spoil the
illusion of being part of the shell. It paints its own strip and is the only
mode that hit-tests window buttons or drags itself.

Painting happens at the window's real resolution — no logical canvas, no
upscaling — and every screen reflows to `content_w` / `content_h`.
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation,
                            QRect, Qt, QTimer)
from PySide6.QtGui import QCursor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app import theme
from app.input import WheelAccumulator

# How far the panel must be dragged from the screen edge before it stops being
# a panel and becomes an ordinary window again.
DETACH_PX = 60

# Handing a drag over to Windows mid-gesture.
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2


class Stage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Qt.Window keeps this a real top-level window (taskbar entry, alt-tab)
        # even though it is frameless; without it a frameless widget can end up
        # with no discoverable window handle at all.
        # An ordinary NATIVE window: real title bar, real drag, real snapping,
        # a taskbar button, and PowerToys/FancyZones support — all for free, and
        # none of it reimplemented. Only the docked panel is frameless, because
        # a side panel with a title bar would not look like one.
        self.setWindowFlags(Qt.WindowType.Window)
        # No caption text: the icon identifies the app, and a label on a small
        # utility window is just noise. A SPACE, not an empty string — Qt
        # substitutes QApplication.applicationName() for an empty title, which
        # put the app's name back in the title bar.
        self.setWindowTitle(" ")
        # The taskbar button and the title bar both take their icon from the
        # window, not from the application, so set it here too.
        try:
            from PySide6.QtGui import QIcon
            ico = (Path(__file__).resolve().parent.parent
                   / "assets" / "icons" / "app.ico")
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
        except Exception:
            pass
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # Small enough that the window can be squeezed down to roughly the width
        # of a row label. The floor is set by the title bar needing room for
        # three window buttons plus a sliver of title.
        self.setMinimumSize(220, 170)
        self.setMouseTracking(True)
        self._rounded = False

        self.stack = None
        self._wheel_acc = WheelAccumulator()
        self._last_click_ms = 0
        self._last_button = Qt.MouseButton.NoButton

        self._animators = []
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._last_tick_time = time.monotonic()

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(200)
        self._resize_timer.timeout.connect(self._on_resize_settled)

        self._drag_origin = None
        self._resize_edge = None
        self._resize_geom = None

        self._hotkey_id = None
        self._hotkey_spec = None
        self._hotkey_filter = None
        self._hotkey_watch = None
        self._panel_mode = False
        self._panel_autohide = True
        self._taskbar_visible = True
        self._hiding = False
        self._shown_at = 0.0
        self._was_active = False

        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(200)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(170)
        self._fade.finished.connect(self._on_hide_finished)

        theme.init_theme(self._on_theme_changed)

    def showEvent(self, event):
        # Deferred until the window actually exists. Calling winId() from
        # __init__ forces native creation before the flags have settled, which
        # on Windows can leave the window unmapped.
        super().showEvent(event)
        if not self._rounded:
            self._rounded = True
            self._apply_native_rounding()

    # ------------------------------------------------------------ geometry

    @property
    def content_w(self) -> int:
        return self.width()

    @property
    def chrome_h(self) -> int:
        """Height of the title strip WE paint. Zero when Windows draws it."""
        return theme.TITLEBAR_H if self._panel_mode else 0

    @property
    def content_h(self) -> int:
        return max(0, self.height() - self.chrome_h)

    @property
    def render_scale(self) -> float:
        """Device pixels per painted pixel. Painting is 1:1 with the window now,
        so this is just the display's DPR — still needed so PDF pages are
        rasterised at true device resolution."""
        return self.devicePixelRatioF()

    def to_content(self, pos: QPointF) -> QPointF:
        return QPointF(pos.x(), pos.y() - self.chrome_h)

    def _apply_native_rounding(self) -> None:
        """Ask DWM for Windows 11 rounded corners and a drop shadow."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)   # ROUND
        except Exception:
            pass

    # -------------------------------------------------------------- wiring

    def set_stack(self, stack):
        self.stack = stack
        self.stack.changed.connect(self.update)

    def _on_theme_changed(self):
        self.update()

    def register(self, anim) -> None:
        if anim not in self._animators:
            self._animators.append(anim)
        self._ensure_timer()

    def unregister(self, anim) -> None:
        if anim in self._animators:
            self._animators.remove(anim)

    def _ensure_timer(self):
        if not self._timer.isActive() and any(a.active for a in self._animators):
            self._last_tick_time = time.monotonic()
            self._timer.start()

    def _on_tick(self):
        now = time.monotonic()
        dt = now - self._last_tick_time
        self._last_tick_time = now

        did_work = False
        any_active = False
        for a in list(self._animators):
            if a.active:
                did_work = True
            a.tick(dt)
            if a.active:
                any_active = True

        if did_work:
            self.update()
        if not any_active:
            self._timer.stop()

    # ------------------------------------------------------- global hotkey

    def install_hotkey(self, spec: str, hotkey_id: int = 1) -> str | None:
        """Claim `spec` system-wide. Returns an error string, or None on success.

        Bound to the thread, not this window: switching the taskbar flag
        recreates the native handle, and a window-bound hotkey would die with it.
        """
        from PySide6.QtCore import QCoreApplication
        from app import hotkey
        try:
            hotkey.register(None, hotkey_id, spec)
        except hotkey.HotkeyError as e:
            return str(e)
        self._hotkey_id = hotkey_id
        self._hotkey_spec = spec
        self._hotkey_filter = hotkey.HotkeyFilter(hotkey_id, self.toggle_panel)
        QCoreApplication.instance().installNativeEventFilter(self._hotkey_filter)

        # Registrations can lapse — a session lock/unlock, an Explorer restart,
        # or another app claiming the combination first. Check periodically and
        # take it back, rather than the shortcut just quietly going dead.
        self._hotkey_watch = QTimer(self)
        self._hotkey_watch.setInterval(15000)
        self._hotkey_watch.timeout.connect(self._verify_hotkey)
        self._hotkey_watch.start()
        return None

    def _verify_hotkey(self) -> None:
        from app import hotkey
        if self._hotkey_id is None or not self._hotkey_spec:
            return
        probe_id = self._hotkey_id + 1000
        try:
            hotkey.register(None, probe_id, self._hotkey_spec)
        except hotkey.HotkeyError:
            return              # still held — by us, which is what we want
        # Claiming it succeeded, so our own registration had gone. Put it back.
        hotkey.unregister(None, probe_id)
        hotkey.unregister(None, self._hotkey_id)
        try:
            hotkey.register(None, self._hotkey_id, self._hotkey_spec)
            print(f"hotkey: {hotkey.describe(self._hotkey_spec)} had lapsed; "
                  f"re-registered", flush=True)
        except hotkey.HotkeyError as e:
            print(f"hotkey: lost and could not be reclaimed: {e}", flush=True)

    # --------------------------------------------------------- taskbar flag

    def set_taskbar_visible(self, visible: bool) -> None:
        """Qt.Tool keeps the window off the taskbar and out of alt-tab; Qt.Window
        puts it back. Switching either way recreates the native handle, so
        geometry has to be restored and the DWM rounding reapplied."""
        if visible == self._taskbar_visible:
            return
        geo = self.geometry()
        was_visible = self.isVisible()
        # Panel: frameless tool window, off the taskbar and out of alt-tab.
        # Window: plain native, so the shell manages it like any other app.
        self.setWindowFlags(Qt.WindowType.Window if visible
                            else (Qt.WindowType.Tool
                                  | Qt.WindowType.FramelessWindowHint))
        self.setGeometry(geo)
        self._taskbar_visible = visible
        self._rounded = False
        if was_visible:
            self.show()
            self._apply_native_rounding()
            self.raise_()
            self.activateWindow()

    # ---------------------------------------------------------- panel mode

    def background_color(self):
        """The window's base colour.

        Docked as a panel it takes the Windows flyout surface colour so it sits
        against the desktop like part of the shell; as an ordinary window it
        keeps the app's own background.
        """
        # The same surface whether docked or floating. Switching colour at the
        # moment of detaching read as a glitch, and there is no reason a window
        # should change appearance simply because it moved.
        return theme.panel_bg()

    def _target_screen_area(self):
        """The screen the user is actually looking at.

        With more than one monitor, self.screen() reports wherever the window
        happens to be — which for a hidden background app is wherever it was
        last, not where attention is. The cursor is the best available proxy.
        """
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.screenAt(QCursor.pos())
        if scr is None:
            scr = self.screen() or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _force_foreground(self) -> None:
        """Actually take the foreground.

        Windows refuses SetForegroundWindow to a process that does not own the
        current foreground window, so a background app calling activateWindow()
        gets a silently unfocused window. Attaching to the foreground thread's
        input queue lifts that restriction for the duration of the call. Without
        this the panel appears unfocused and auto-hide dismisses it immediately,
        which looks exactly like the hotkey being dead.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self.winId())
            fg = user32.GetForegroundWindow()
            this_tid = kernel32.GetCurrentThreadId()
            fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            if fg_tid and fg_tid != this_tid:
                user32.AttachThreadInput(fg_tid, this_tid, True)
                try:
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                finally:
                    user32.AttachThreadInput(fg_tid, this_tid, False)
            else:
                user32.SetForegroundWindow(hwnd)
        except Exception as e:
            print(f"force_foreground: {e}")

    @staticmethod
    def panel_geometry(area, width: int):
        """Left-edge strip filling the usable desktop height."""
        w = max(1, min(int(width), area.width()))
        return area.x(), area.y(), w, area.height()

    def show_panel(self, width: int | None = None, animate: bool = True) -> None:
        from app import config
        area = self._target_screen_area()
        w = width if width is not None else int(config.get("panel_width") or 420)
        x, y, w, h = self.panel_geometry(area, max(w, self.minimumWidth()))

        self._panel_mode = True
        self._hiding = False
        self._shown_at = time.monotonic()
        self._was_active = False        # armed only once it genuinely has focus
        self.set_taskbar_visible(False)     # a summoned panel is not a taskbar app
        self._slide.stop()
        self._fade.stop()

        if not animate:
            self.setGeometry(x, y, w, h)
            self.setWindowOpacity(1.0)
            self.show()
            self.raise_()
            self.activateWindow()
            self._force_foreground()
            return

        # Start just off the left edge and slide in.
        self.setGeometry(x - w, y, w, h)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()

        self._force_foreground()

        self._slide.setStartValue(QPoint(x - int(w * 0.35), y))
        self._slide.setEndValue(QPoint(x, y))
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._slide.start()
        self._fade.start()

    def save_nav(self) -> None:
        """Write down which folders are open and where the cursor sits, so the
        next launch — after a restart, a crash or a sign-out — reopens there."""
        if not self.stack:
            return
        try:
            from app import config
            state = config.load_state()
            state["nav"] = self.stack.snapshot()
            config.save_state(state)
        except Exception as e:
            print(f"could not save navigation: {e}", flush=True)

    def hide_panel(self, animate: bool = True) -> None:
        self.save_nav()
        self._panel_mode = False
        if not animate or not self.isVisible():
            self._slide.stop()
            self._fade.stop()
            self.setWindowOpacity(1.0)
            self.hide()
            return

        g = self.geometry()
        self._slide.stop()
        self._fade.stop()
        self._slide.setStartValue(g.topLeft())
        self._slide.setEndValue(QPoint(g.x() - int(g.width() * 0.35), g.y()))
        self._slide.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._hiding = True
        self._slide.start()
        self._fade.start()

    def _on_hide_finished(self) -> None:
        if self._hiding:
            self._hiding = False
            self.hide()
            self.setWindowOpacity(1.0)

    def toggle_panel(self) -> None:
        """Summon the panel; press again to dismiss it.

        Only dismisses when the panel itself is up. Testing isVisible() and
        isActiveWindow() instead meant that pressing the hotkey while the app
        was open as an ordinary window slid that window away rather than
        summoning anything — which looked exactly like the hotkey being dead.
        """
        print(f"hotkey fired: panel_mode={self._panel_mode} "
              f"visible={self.isVisible()} hiding={self._hiding}", flush=True)
        if self._panel_mode and self.isVisible() and not self._hiding:
            self.hide_panel()
        else:
            self.show_panel()
            print(f"  -> panel at {self.geometry()} visible={self.isVisible()}",
                  flush=True)

    def changeEvent(self, event) -> None:
        # Dismiss on focus loss, the way the Widgets board does — but only when
        # summoned as a panel, so an ordinary window is never yanked away.
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                # Only once the panel has genuinely held focus does losing it
                # mean anything.
                self._was_active = True
            elif self.should_autohide():
                self.hide_panel()
        super().changeEvent(event)

    def should_autohide(self) -> bool:
        """Whether losing focus right now should dismiss the panel.

        Kept as a pure decision so it can be tested without needing to steal
        real focus from another application. Two guards, each for a bug that
        made the hotkey look dead:

        - `_was_active`: a background process cannot always take the foreground
          on Windows, and a panel that never got focus must not treat a stray
          deactivation as a dismissal.
        - the grace period: switching to Qt.Tool and animating in produces a
          burst of activation churn, which would otherwise dismiss the panel
          before it finished appearing.
        """
        return (self._panel_mode and self._panel_autohide and self._was_active
                and time.monotonic() - self._shown_at > 0.6)

    def closeEvent(self, event) -> None:
        # Remember the size and position the user settled on. Skipped while
        # maximised, so restoring does not reopen at full-screen dimensions.
        #
        # The hotkey is deliberately NOT released here. It is bound to the thread
        # rather than this window, and closing the window does not quit the app —
        # it keeps running in the tray. Releasing it here left the shortcut dead
        # for the rest of the session, and clearing _hotkey_id also made
        # _verify_hotkey return early forever, so the watchdog could never take it
        # back. Windows frees thread hotkeys when the process exits, so there is
        # nothing to clean up.
        self.save_nav()
        try:
            from app import config
            # Panel geometry is derived from the screen, not chosen by the user,
            # so it must not overwrite the remembered window size.
            if not self.isMaximized() and not self._panel_mode:
                g = self.geometry()
                config.set_value("window", {"w": g.width(), "h": g.height(),
                                            "x": g.x(), "y": g.y()})
        except Exception as e:
            print(f"could not save window geometry: {e}")
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize_settled(self) -> None:
        if self.stack and self.stack.top:
            self.stack.top.on_scale_changed()

    # ---------------------------------------------------------- panel edges
    #
    # The docked panel deliberately has no minimise/maximise/close buttons: it
    # is dismissed with the hotkey or by clicking away, and dragging its title
    # strip off the edge turns it into an ordinary window with Windows' own.

    def _edge_at(self, x, y):
        if self.isMaximized():
            return None
        m = theme.RESIZE_MARGIN
        w, h = self.width(), self.height()
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        return None

    _CURSORS = {
        "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
        "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
        "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    }

    # --------------------------------------------------------------- input

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()

        # A drag that outlives its button is what made the window follow the
        # mouse on hover: if a release is missed (it happens when the pointer
        # leaves the window, or the native handle is recreated mid-drag) the
        # state would never clear. Trust the live button state, not the memory
        # of a press.
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._drag_origin = None
            self._resize_edge = None
            self._resize_geom = None

        if not self._panel_mode:
            return          # Windows handles moving and resizing a real window

        if self._resize_edge and self._resize_geom:
            self._perform_resize(event.globalPosition())
            return
        if self._drag_origin is not None:
            self.move((event.globalPosition() - self._drag_origin).toPoint())
            # Dragged off the edge: it is a window now, so give it back its
            # taskbar button and stop auto-hiding it.
            if self._panel_mode:
                area = self.screen().availableGeometry()
                if abs(self.x() - area.x()) > DETACH_PX:
                    self._detach_to_window()
            return

        edge = self._edge_at(x, y)
        self.setCursor(QCursor(self._CURSORS[edge] if edge
                               else Qt.CursorShape.ArrowCursor))

    def _detach_to_window(self) -> None:
        """Turn the dragged panel into an ordinary window without dropping the drag.

        set_taskbar_visible destroys and recreates the native window, which
        takes the OS mouse capture with it — the drag simply died and had to be
        started again. Handing the drag to Windows itself (ReleaseCapture, then
        WM_NCLBUTTONDOWN with HTCAPTION) makes the new window pick it up mid-
        gesture, so the pointer never lets go.
        """
        self._panel_mode = False
        self._drag_origin = None            # Windows owns the drag from here
        self.set_taskbar_visible(True)

        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            u.ReleaseCapture()
            u.SendMessageW(int(self.winId()), WM_NCLBUTTONDOWN, HTCAPTION, 0)
        except Exception as e:
            print(f"detach drag handoff: {e}")

    def _perform_resize(self, gpos):
        g = QRect(self._resize_geom)
        dx = int(gpos.x() - self._resize_origin.x())
        dy = int(gpos.y() - self._resize_origin.y())
        e = self._resize_edge
        if "l" in e:
            g.setLeft(g.left() + dx)
        if "r" in e:
            g.setRight(g.right() + dx)
        if "t" in e:
            g.setTop(g.top() + dy)
        if "b" in e:
            g.setBottom(g.bottom() + dy)
        if g.width() >= self.minimumWidth() and g.height() >= self.minimumHeight():
            self.setGeometry(g)

    def mouseDoubleClickEvent(self, event):
        if not self._panel_mode:
            return
        y = event.position().y()
        if y < theme.TITLEBAR_H:
            self._toggle_max()

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        btn = event.button()

        if btn == Qt.MouseButton.LeftButton and self._panel_mode:
            edge = self._edge_at(x, y)
            if edge:
                self._resize_edge = edge
                self._resize_geom = self.geometry()
                self._resize_origin = event.globalPosition()
                return
            if y < theme.TITLEBAR_H:
                self._drag_origin = event.globalPosition() - self.frameGeometry().topLeft()
                return

        if not self.stack or not self.stack.top or self.stack.is_transitioning:
            return
        if self._panel_mode and y < theme.TITLEBAR_H:
            return

        now_ms = int(time.monotonic() * 1000)
        if btn == self._last_button and now_ms - self._last_click_ms < 120:
            return
        self._last_click_ms = now_ms
        self._last_button = btn

        c = self.to_content(event.position())
        if btn == Qt.MouseButton.LeftButton:
            self.stack.top.on_left_click(c.x(), c.y())
        elif btn == Qt.MouseButton.RightButton:
            self.stack.top.on_right_click(c.x(), c.y())
        elif btn == Qt.MouseButton.MiddleButton:
            self.stack.top.on_middle_click(c.x(), c.y())

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        self._resize_edge = None
        self._resize_geom = None

    def wheelEvent(self, event) -> None:
        if not self.stack or not self.stack.top or self.stack.is_transitioning:
            return
        now_ms = int(time.monotonic() * 1000)
        # Wheel DOWN reports a negative angleDelta; negating makes it +1 = forward.
        steps = self._wheel_acc.feed(-event.angleDelta().y(), now_ms)
        if steps != 0:
            self.stack.top.on_wheel(steps)

    # --------------------------------------------------------------- paint

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        p.fillRect(self.rect(), self.background_color())

        if self.stack and self.stack.top:
            p.save()
            p.translate(0, self.chrome_h)
            p.setClipRect(0, 0, self.content_w, self.content_h)
            self.stack.paint_transition(p)
            p.restore()

        if self._panel_mode:
            self._paint_titlebar(p)

    def _paint_titlebar(self, p: QPainter):
        w = self.width()
        h = theme.TITLEBAR_H
        p.fillRect(0, 0, w, h, theme.panel_bg())

        title = ""
        if self.stack and self.stack.top:
            title = self.stack.top.title or ""

        # Back affordance, only when there is somewhere to go back to.
        x_text = 16
        if self.stack and self.stack.depth > 1:
            p.setPen(QPen(theme.color("TEXT_DIM"), 1.6,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            cx, cy = 20, h / 2
            p.drawLine(QPointF(cx + 3, cy - 5), QPointF(cx - 2, cy))
            p.drawLine(QPointF(cx - 2, cy), QPointF(cx + 3, cy + 5))
            x_text = 38

        p.setFont(theme.font("F_TITLE"))
        fm = QFontMetrics(p.font())
        avail = w - x_text - 16
        if avail >= 24:          # below this an elided title is just "…"
            p.setPen(theme.color("TEXT"))
            p.drawText(x_text, int(h / 2 + fm.capHeight() / 2),
                       fm.elidedText(title, Qt.TextElideMode.ElideRight, avail))
