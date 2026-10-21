"""End-to-end checks that exercise the real paint path.

The per-screen tests call `screen.paint()` directly, which skips Stage.paintEvent
and ScreenStack.paint_transition entirely. That blind spot once let a mis-indented
module-level function silently strip three methods off ScreenStack — the app
imported, every suite passed, and the window died on its first repaint.
"""
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint                                # noqa: E402
from PySide6.QtGui import QImage                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

import main as app_main                                          # noqa: E402
from app import config, theme                                    # noqa: E402
from app.application import Stage                                # noqa: E402
from app.library.scanner import scan                             # noqa: E402
from app.navigation import Screen, ScreenStack                   # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

REQUIRED_STACK_METHODS = ["push", "pop", "bump", "_bump_return", "_trans_done",
                          "paint_transition", "relist", "sync_watches"]
REQUIRED_SCREEN_METHODS = ["paint", "on_wheel", "on_left_click", "on_right_click",
                           "on_middle_click", "on_enter", "on_leave",
                           "on_scale_changed"]


def test_window_always_fits_on_screen():
    from PySide6.QtCore import QRect
    from main import fit_window

    screen = QRect(0, 0, 1536, 816)          # the real desktop this was hit on
    cases = {
        "oversized saved size": {"w": 1280, "h": 960, "x": None, "y": None},
        "absurd saved size": {"w": 6000, "h": 4000, "x": None, "y": None},
        "off-screen position": {"w": 900, "h": 600, "x": 5000, "y": -900},
        "negative position": {"w": 900, "h": 600, "x": -400, "y": -400},
        "empty config": {},
    }
    for label, saved in cases.items():
        x, y, w, h = fit_window(screen, saved, 560, 380)
        assert w <= screen.width() and h <= screen.height(), f"{label}: {w}x{h}"
        assert x >= screen.x() and y >= screen.y(), f"{label}: origin {x},{y}"
        assert x + w <= screen.right() + 1, f"{label}: right edge off-screen"
        assert y + h <= screen.bottom() + 1, f"{label}: bottom edge off-screen"
        # The title strip must be reachable, or the window cannot be moved.
        assert y >= 0, f"{label}: title bar above the top of the screen"

    # A desktop smaller than the app's own minimum must still yield a usable rect.
    tiny = QRect(0, 0, 480, 320)
    x, y, w, h = fit_window(tiny, {}, 560, 380)
    assert (x, y) == (0, 0) and w <= 560 and h <= 380, (x, y, w, h)
    print(f"PASS (g): window placement fits {len(cases)} bad configs onto a "
          f"1536x816 desktop and survives a screen smaller than the minimum.")


def test_public_surface_intact():
    for name in REQUIRED_STACK_METHODS:
        assert callable(getattr(ScreenStack, name, None)), \
            f"ScreenStack.{name} is missing — check indentation in navigation.py"
    for name in REQUIRED_SCREEN_METHODS:
        assert callable(getattr(Screen, name, None)), f"Screen.{name} is missing"
    print(f"PASS (a): ScreenStack and Screen expose all "
          f"{len(REQUIRED_STACK_METHODS) + len(REQUIRED_SCREEN_METHODS)} "
          f"required methods.")


def build_real_app():
    config.init()
    stage = Stage()
    stage.resize(1100, 720)
    stack = ScreenStack(stage)
    stage.set_stack(stack)
    stack.root_factory = lambda: app_main.build_root_menu(stack)
    stack.push(app_main.build_root_menu(stack))
    return stage, stack, None


def render_stage(stage) -> QImage:
    """Full widget render — goes through paintEvent and paint_transition."""
    img = QImage(stage.width(), stage.height(), QImage.Format.Format_ARGB32)
    img.fill(0)
    stage.render(img, QPoint(0, 0))
    return img


def test_stage_paints_without_error():
    stage, _stack, _root = build_real_app()
    img = render_stage(stage)
    assert not img.isNull() and img.width() == 1100
    # The title bar must actually be painted, not left transparent.
    assert img.pixelColor(300, theme.TITLEBAR_H // 2).alpha() == 255
    print("PASS (b): the full Stage paint path runs clean, title bar included.")


def test_navigation_paints_at_every_depth():
    stage, stack, _root = build_real_app()
    depths = [stack.depth]
    for _ in range(3):
        before = stack.depth
        stack.top.on_left_click(0, 0)
        if stack.depth == before:
            break
        render_stage(stage)
        depths.append(stack.depth)
    assert max(depths) > 1, "never navigated anywhere"

    while stack.depth > 1:
        stack.top.on_right_click(0, 0)
        render_stage(stage)          # mid-transition frames must paint too
    assert stack.depth == 1
    print(f"PASS (c): pushed and popped through depths {depths}, "
          f"painting at each one.")


def test_root_bump_paints():
    stage, stack, _root = build_real_app()
    assert stack.depth == 1
    stack.top.on_right_click(0, 0)   # at the root this bumps rather than pops
    assert stack.depth == 1, "right click at the root must not pop"
    stack.bump_anim.value = 4.0      # mid-bump frame
    render_stage(stage)
    print("PASS (d): the root bump runs and paints without popping.")


def test_resize_reflows_without_error():
    stage, _stack, _root = build_real_app()
    sizes = [(stage.minimumWidth(), stage.minimumHeight()),
             (260, 200), (400, 300), (640, 420), (900, 600), (1600, 1000), (1100, 720)]
    for w, h in sizes:
        stage.resize(w, h)
        img = render_stage(stage)
        assert img.width() == w and img.height() == h
    print(f"PASS (e): renders cleanly at {len(sizes)} sizes, "
          f"down to {stage.minimumWidth()}x{stage.minimumHeight()}.")


def test_docked_panel_has_no_window_buttons():
    """Docked, the title strip is the panel's own: a title and a drag handle,
    with no minimise/maximise/close. Pressing where the close button used to
    sit must start a drag, never close or minimise the panel."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    stage, _stack, _root = build_real_app()
    stage._panel_mode = True
    stage.resize(420, 700)
    assert not hasattr(stage, "_button_rects")

    corner = QPointF(stage.width() - 20, theme.TITLEBAR_H / 2)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, corner, stage.mapToGlobal(corner),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    stage.mousePressEvent(ev)
    assert stage._drag_origin is not None, "title-strip corner should drag"
    assert not stage.isMinimized()
    img = render_stage(stage)
    assert img.width() == 420
    print("PASS (h): the docked panel's title strip has no window buttons; its "
          "corner is a drag handle.")


def test_both_themes_paint():
    for mode in ("dark", "light"):
        theme.set_mode(mode)
        stage, _stack, _root = build_real_app()
        img = render_stage(stage)
        assert img.pixelColor(5, 5).alpha() == 255, f"{mode} background not painted"
    theme.set_mode(None)
    print("PASS (f): both palettes paint a full opaque window.")


if __name__ == "__main__":
    failed = 0
    for fn in (test_window_always_fits_on_screen,
               test_public_surface_intact,
               test_stage_paints_without_error,
               test_navigation_paints_at_every_depth,
               test_root_bump_paints,
               test_resize_reflows_without_error,
               test_docked_panel_has_no_window_buttons,
               test_both_themes_paint):
        try:
            fn()
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)
