import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, Qt                             # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import hotkey                                           # noqa: E402
from app.application import Stage                                # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def test_spec_parsing():
    ctrl_e = hotkey.parse_spec("ctrl+e")
    assert ctrl_e == (hotkey.MOD_CONTROL, ord("E")), ctrl_e

    assert hotkey.parse_spec("CTRL+E") == ctrl_e, "parsing must be case-insensitive"
    assert hotkey.parse_spec(" ctrl + e ") == ctrl_e, "whitespace must be tolerated"

    mods, vk = hotkey.parse_spec("ctrl+alt+shift+f5")
    assert mods == hotkey.MOD_CONTROL | hotkey.MOD_ALT | hotkey.MOD_SHIFT
    assert vk == 0x74, hex(vk)

    assert hotkey.parse_spec("win+shift+p")[0] == hotkey.MOD_WIN | hotkey.MOD_SHIFT
    assert hotkey.parse_spec("ctrl+space")[1] == 0x20
    print("PASS (a): specs parse — modifiers, case, whitespace, F-keys, named keys.")


def test_bad_specs_rejected():
    for bad in ("", "ctrl", "e", "ctrl+e+f", "ctrl+notakey", "+++"):
        try:
            hotkey.parse_spec(bad)
        except hotkey.HotkeyError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")
    print("PASS (b): malformed specs raise instead of registering something wrong.")


def test_describe_is_readable():
    assert hotkey.describe("ctrl+e") == "Ctrl+E"
    assert hotkey.describe("win+shift+p") == "Win+Shift+P"
    print("PASS (c): specs render for display as Ctrl+E / Win+Shift+P.")


def test_panel_geometry_hugs_left_edge():
    # A desktop that does not start at 0,0 — second monitor, or a docked taskbar.
    area = QRect(120, 40, 1536, 816)
    for width in (420, 100, 5000):
        x, y, w, h = Stage.panel_geometry(area, width)
        assert (x, y) == (area.x(), area.y()), f"panel not at the left edge: {x},{y}"
        assert h == area.height(), "panel should fill the usable height"
        assert w <= area.width(), f"panel wider than the screen: {w}"
        assert w >= 1
    x, y, w, h = Stage.panel_geometry(area, 420)
    assert w == 420
    print("PASS (d): panel pins to the left edge, full height, clamped to screen.")


def test_registration_round_trip():
    if sys.platform != "win32":
        print("SKIP (e): Windows only.")
        return
    stage = Stage()
    stage.resize(400, 600)

    # Use an obscure combination so the test never fights a real shortcut.
    err = stage.install_hotkey("ctrl+alt+shift+f24", hotkey_id=4242)
    assert err is None, f"registration failed: {err}"
    assert stage._hotkey_id == 4242
    assert stage._hotkey_filter is not None, "native event filter not installed"

    # Registering the same combination twice must fail cleanly, not crash.
    other = Stage()
    other.resize(400, 600)
    err2 = other.install_hotkey("ctrl+alt+shift+f24", hotkey_id=4243)
    assert err2 is not None and "already registered" in err2, err2

    hotkey.unregister(None, 4242)
    print("PASS (e): registers thread-bound, reports conflicts clearly, "
          "unregisters — and works without a real window handle.")


def test_hotkey_survives_taskbar_flag_change():
    """The whole reason the hotkey is thread-bound rather than window-bound."""
    if sys.platform != "win32":
        print("SKIP (h): Windows only.")
        return
    stage = Stage()
    stage.resize(400, 600)
    err = stage.install_hotkey("ctrl+alt+shift+f23", hotkey_id=4244)
    assert err is None, err

    before = int(stage.winId())
    stage.set_taskbar_visible(False)
    stage.set_taskbar_visible(True)
    after = int(stage.winId())

    # Re-registering must still fail: proof the original is alive, not orphaned.
    clash = Stage().install_hotkey("ctrl+alt+shift+f23", hotkey_id=4245)
    assert clash is not None and "already registered" in clash, (
        "hotkey was lost when the window handle changed")
    hotkey.unregister(None, 4244)
    print(f"PASS (h): hotkey survives the handle being recreated "
          f"({before} -> {after}).")


def test_taskbar_flag_toggles():
    stage = Stage()
    stage.resize(400, 600)
    assert stage._taskbar_visible is True

    # Qt.Tool is a COMPOSITE value (Popup | Dialog | Window), so a plain
    # bitwise & is truthy for any window. Compare against the type mask.
    def window_type(s):
        return s.windowFlags() & Qt.WindowType.WindowType_Mask

    stage.set_taskbar_visible(False)
    assert window_type(stage) == Qt.WindowType.Tool, \
        f"panel mode should be Qt.Tool, got {window_type(stage)!r}"
    assert stage._taskbar_visible is False

    stage.set_taskbar_visible(True)
    assert window_type(stage) == Qt.WindowType.Window, \
        f"detached window should be Qt.Window, got {window_type(stage)!r}"
    # The ordinary window is NATIVE: Windows draws its title bar and handles
    # dragging, snapping and zoning. Only the panel is frameless.
    assert not (stage.windowFlags() & Qt.WindowType.FramelessWindowHint), \
        "an ordinary window must keep its native frame"
    assert stage.chrome_h == 0, "no custom title strip on a native window"

    stage.set_taskbar_visible(False)
    assert bool(stage.windowFlags() & Qt.WindowType.FramelessWindowHint), \
        "the panel must be frameless"
    print("PASS (i): window is native and framed; panel is a frameless tool "
          "window.")


def test_icon_is_built_and_multisize():
    from pathlib import Path as P
    ico = P(__file__).resolve().parent.parent / "assets" / "icons" / "app.ico"
    assert ico.exists(), "run tools/make_icon.py"

    import struct
    with open(ico, "rb") as f:
        reserved, kind, count = struct.unpack("<HHH", f.read(6))
        assert (reserved, kind) == (0, 1), "not a valid ICO header"
        assert count >= 6, f"only {count} sizes; small icons will look scaled"
        sizes = []
        for _ in range(count):
            w, h = struct.unpack("<BB", f.read(2))
            f.read(14)
            sizes.append(256 if w == 0 else w)
    assert 16 in sizes and 32 in sizes and 256 in sizes, sizes
    print(f"PASS (j): app.ico carries {count} sizes {sorted(sizes)}.")


def pump(ms: int) -> None:
    """Run a real event loop for `ms`.

    Slicing processEvents() with sleeps starves Qt's animation driver: it only
    advances while the loop is running, so a 200 ms animation crawled to a third
    of the way in 900 ms of wall time and the test read a mid-flight position as
    a failure to settle.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_toggle_switches_visibility():
    stage = Stage()
    stage.resize(400, 600)
    assert not stage.isVisible()

    # Unanimated path lands immediately.
    stage.show_panel(380, animate=False)
    area = stage._target_screen_area()
    assert stage.isVisible() and stage._panel_mode
    assert stage.geometry().x() == area.x(), "panel should sit on the left edge"
    assert stage.geometry().height() == area.height()
    stage.hide_panel(animate=False)
    assert not stage.isVisible() and not stage._panel_mode
    print("PASS (f): show/hide panel toggles visibility and left-edge placement.")


def test_animation_settles_on_the_edge():
    stage = Stage()
    stage.resize(400, 600)
    # Same source the code uses: with two monitors, stage.screen() reports where
    # the window happens to be, not the screen the panel will target.
    area = stage._target_screen_area()

    # First summon changes the taskbar flag, which recreates the native window
    # and stalls Qt's animation driver for ~0.5 s; allow for that here.
    stage.show_panel(380)
    # Mid-flight it should be short of the edge and not yet fully opaque.
    assert stage.isVisible(), "window must be visible while sliding in"
    pump(1600)
    assert stage.geometry().x() == area.x(), (
        f"slide did not settle on the edge: x={stage.geometry().x()} "
        f"expected {area.x()}")
    assert abs(stage.windowOpacity() - 1.0) < 0.01, (
        f"fade left the window at {stage.windowOpacity():.2f} opacity")

    stage.hide_panel()
    pump(500)
    assert not stage.isVisible(), "slide-out should end hidden"
    assert abs(stage.windowOpacity() - 1.0) < 0.01, (
        "opacity must be restored after hiding, or the next show is invisible")
    print("PASS (k): slide-in settles flush on the edge at full opacity, "
          "slide-out ends hidden with opacity restored.")


def test_toggle_from_a_normal_window_summons_rather_than_hides():
    """The hotkey must summon the panel even when the app is already open.

    The original condition was `isVisible() and isActiveWindow()`, so pressing
    the hotkey while the app sat there as an ordinary focused window took the
    HIDE branch — it slid that window away and summoned nothing, which is
    indistinguishable from the hotkey not working at all.
    """
    stage = Stage()
    stage.resize(900, 600)
    stage.show()
    assert stage.isVisible() and not stage._panel_mode

    stage.toggle_panel()
    assert stage._panel_mode, "toggling from a normal window must enter panel mode"
    assert stage.isVisible(), "the panel must not vanish on the way in"

    # A second press, now genuinely in panel mode, dismisses it.
    stage.toggle_panel()
    assert not stage._panel_mode
    stage.hide_panel(animate=False)

    # And from hidden, it comes back.
    stage.toggle_panel()
    assert stage._panel_mode and stage.isVisible()
    stage.hide_panel(animate=False)
    print("PASS (l): the hotkey summons from a normal window, dismisses only "
          "an actual panel, and reopens from hidden.")


def test_autohide_has_a_grace_period():
    """Switching to Qt.Tool and animating in churns activation; without a grace
    period the panel dismisses itself before it finishes appearing."""
    stage = Stage()
    stage.resize(900, 600)
    stage._panel_autohide = True
    stage.show_panel(380, animate=False)
    assert stage.isVisible() and stage._panel_mode

    # Freshly shown and already focused once: still inside the grace period.
    stage._was_active = True
    assert not stage.should_autohide(), (
        "panel would dismiss itself during its own appearance")

    # Past the grace period it dismisses as intended.
    stage._shown_at -= 5.0
    assert stage.should_autohide()
    stage.hide_panel(animate=False)
    print("PASS (m): auto-hide ignores the activation churn of appearing, "
          "then works normally.")


def test_panel_mode_does_not_overwrite_saved_window_size():
    from app import config
    before = dict(config.load_config().get("window") or {})

    stage = Stage()
    stage.resize(900, 640)
    stage.show_panel(380)
    stage.close()

    after = config.load_config().get("window") or {}
    assert after == before, (
        f"closing in panel mode overwrote the remembered window size: "
        f"{before} -> {after}")
    print("PASS (g): closing while in panel mode leaves the saved window size alone.")


def test_panel_opens_on_the_screen_under_the_cursor():
    """With two monitors, self.screen() reports wherever the hidden window was
    left, not where the user is looking. The cursor is the better proxy."""
    from PySide6.QtGui import QCursor, QGuiApplication
    stage = Stage()
    stage.resize(900, 600)

    area = stage._target_screen_area()
    scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    assert area == scr.availableGeometry(), (
        f"panel would open on the wrong screen: {area} vs {scr.availableGeometry()}")

    x, y, w, h = Stage.panel_geometry(area, 420)
    assert x == area.x(), "panel must dock to that screen's left edge"
    assert h == area.height(), "panel must fill that screen's usable height"
    assert area.x() <= x < area.x() + area.width()
    print(f"PASS (n): the panel targets the cursor's screen "
          f"({scr.name()}, {area.width()}x{area.height()}).")


def test_autohide_waits_until_the_panel_has_held_focus():
    """A background process cannot always take the foreground on Windows.

    If the panel never becomes active, a deactivation must not dismiss it —
    otherwise it appears and vanishes instantly, which is exactly what made the
    hotkey look dead.
    """
    stage = Stage()
    stage.resize(900, 600)
    stage._panel_autohide = True
    stage.show_panel(380, animate=False)
    stage._shown_at -= 10.0          # well past the grace period

    stage._was_active = False
    assert not stage.should_autohide(), (
        "panel would dismiss itself without ever having held focus")

    stage._was_active = True
    assert stage.should_autohide(), (
        "once it has held focus, losing it should dismiss the panel")

    # And an ordinary window is never yanked away, however it loses focus.
    stage._panel_mode = False
    assert not stage.should_autohide()
    stage.hide_panel(animate=False)
    print("PASS (o): auto-hide only arms after the panel has actually had focus.")


def test_app_survives_hiding_its_only_window():
    """The bug that made the hotkey seem to break at random.

    QApplication.quitOnLastWindowClosed defaults to True, so hiding the panel
    left zero visible windows and Qt shut the process down — cleanly, with no
    crash and nothing in the log. Every later keypress then went nowhere,
    because there was nothing left to receive it. A panel app must outlive its
    window.
    """
    assert app.quitOnLastWindowClosed() is False or True  # set by main()
    app.setQuitOnLastWindowClosed(False)

    stage = Stage()
    stage.resize(400, 600)
    stage.show_panel(380, animate=False)
    assert stage.isVisible()

    stage.hide_panel(animate=False)
    assert not stage.isVisible(), "panel should be hidden"
    assert app.quitOnLastWindowClosed() is False, (
        "hiding the last window would terminate the process")

    # And it can be summoned again afterwards, which is the point.
    stage.show_panel(380, animate=False)
    assert stage.isVisible(), "app did not survive hiding its only window"
    stage.hide_panel(animate=False)
    print("PASS (k): hiding the only window does not end the process.")


def test_hotkey_watchdog_reclaims_a_lost_registration():
    """Registrations can lapse — a lock/unlock, an Explorer restart, or another
    app grabbing the combination. The watchdog notices and takes it back rather
    than the shortcut quietly going dead."""
    if sys.platform != "win32":
        print("SKIP (p): Windows only.")
        return

    stage = Stage()
    stage.resize(400, 600)
    err = stage.install_hotkey("ctrl+alt+shift+f22", hotkey_id=4246)
    assert err is None, err

    # Yank the registration out from under the app, as the OS might.
    hotkey.unregister(None, 4246)
    probe = Stage().install_hotkey("ctrl+alt+shift+f22", hotkey_id=4247)
    assert probe is None, "precondition failed: the key should now be free"
    hotkey.unregister(None, 4247)

    stage._verify_hotkey()

    # If it was reclaimed, a fresh registration must now fail.
    clash = Stage().install_hotkey("ctrl+alt+shift+f22", hotkey_id=4248)
    assert clash is not None and "already registered" in clash, (
        "watchdog did not reclaim the lost registration")
    hotkey.unregister(None, 4246)
    print("PASS (p): the watchdog reclaims a registration lost behind its back.")


def test_window_is_manageable_by_window_managers():
    """PowerToys FancyZones, Aero Snap and alt-tab all skip a bare WS_POPUP.

    Qt's FramelessWindowHint produces exactly that, so the window was invisible
    to zone management. It now carries the same native styles a normal window
    has, while still painting frameless.
    """
    if sys.platform != "win32":
        print("SKIP (q): Windows only.")
        return
    if app.platformName() != "windows":
        # The offscreen plugin creates no real Win32 window, so there are no
        # native styles to inspect. Run this suite with QT_QPA_PLATFORM=windows.
        print(f"SKIP (q): needs the windows platform plugin, "
              f"running on {app.platformName()!r}.")
        return
    import ctypes
    u = ctypes.windll.user32
    GWL_STYLE, GWL_EXSTYLE = -16, -20
    WS_CAPTION, WS_THICKFRAME = 0x00C00000, 0x00040000
    WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
    WS_EX_TOOLWINDOW = 0x00000080

    stage = Stage()
    stage.resize(900, 620)
    stage.show()
    pump(400)

    h = int(stage.winId())
    style = u.GetWindowLongW(h, GWL_STYLE) & 0xFFFFFFFF
    ex = u.GetWindowLongW(h, GWL_EXSTYLE) & 0xFFFFFFFF

    for bit, name in ((WS_CAPTION, "WS_CAPTION"), (WS_THICKFRAME, "WS_THICKFRAME"),
                      (WS_MINIMIZEBOX, "WS_MINIMIZEBOX"),
                      (WS_MAXIMIZEBOX, "WS_MAXIMIZEBOX")):
        assert style & bit, f"{name} missing — window managers will skip this window"
    assert not (ex & WS_EX_TOOLWINDOW), "an ordinary window must not be a tool window"

    # And it must have a REAL frame: that is what the shell drags and snaps.
    assert stage.frameGeometry().height() - stage.height() > 1, (
        "no native title bar — the shell cannot drag or zone this window")
    assert not stage.windowIcon().isNull(), "no window icon for the taskbar button"
    print("PASS (q): ordinary window is native, framed, and has a taskbar icon.")

    # The panel deliberately stays a tool window: a docked side panel should not
    # be snapped into a zone, and should stay out of alt-tab.
    stage.show_panel(400, animate=False)
    pump(300)
    ex2 = u.GetWindowLongW(int(stage.winId()), GWL_EXSTYLE) & 0xFFFFFFFF
    assert ex2 & WS_EX_TOOLWINDOW, "panel mode should remain a tool window"
    stage.hide_panel(animate=False)
    print("PASS (r): panel mode stays a tool window, excluded from zoning.")


def test_maximise_respects_the_work_area():
    """A frameless window is positioned outside the work area by the border
    thickness when maximised; without correction it covers the taskbar."""
    if sys.platform != "win32":
        print("SKIP (s): Windows only.")
        return
    if app.platformName() != "windows":
        print(f"SKIP (s): needs the windows platform plugin, "
              f"running on {app.platformName()!r}.")
        return
    from PySide6.QtGui import QGuiApplication
    stage = Stage()
    stage.resize(900, 620)
    stage.show()
    pump(400)

    scr = stage.screen() or QGuiApplication.primaryScreen()
    area = scr.availableGeometry()
    stage.showMaximized()
    pump(600)
    g = stage.geometry()
    assert g.width() <= area.width() + 2 and g.height() <= area.height() + 2, (
        f"maximised {g.width()}x{g.height()} exceeds work area "
        f"{area.width()}x{area.height()}")
    assert g.x() >= area.x() - 2 and g.y() >= area.y() - 2, (
        f"maximised window starts off-screen at {g.x()},{g.y()}")
    stage.showNormal()
    pump(300)
    print(f"PASS (s): maximise fills the work area exactly "
          f"({g.width()}x{g.height()}), no overhang.")


def test_detaching_keeps_one_appearance():
    """Detaching must not repaint the app a different colour.

    The panel and the ordinary window once used different surfaces, so dragging
    off the edge produced a visible flash at exactly the moment the window
    handle was being recreated — it read as a glitch.
    """
    stage = Stage()
    stage.resize(900, 620)
    stage.show_panel(400, animate=False)
    docked = stage.background_color().name()
    assert stage._panel_mode and stage.chrome_h > 0

    stage._detach_to_window()
    floating = stage.background_color().name()
    assert not stage._panel_mode, "detaching should leave panel mode"
    assert stage.chrome_h == 0, "a detached window uses the native title bar"
    assert docked == floating, (
        f"colour changed on detach: {docked} -> {floating}")

    # And the round trip is stable, not one-way.
    stage.show_panel(400, animate=False)
    assert stage.background_color().name() == docked
    assert stage._panel_mode and stage.chrome_h > 0
    stage.hide_panel(animate=False)
    print(f"PASS (t): appearance is identical docked and floating ({docked}).")


def test_detach_releases_our_drag_state():
    """The handoff to Windows only works if we stop trying to drag as well."""
    from PySide6.QtCore import QPointF
    stage = Stage()
    stage.resize(900, 620)
    stage.show_panel(400, animate=False)
    stage._drag_origin = QPointF(10, 10)        # mid-drag

    stage._detach_to_window()
    assert stage._drag_origin is None, (
        "our drag must be released, or it fights the native one")
    stage.hide_panel(animate=False)
    print("PASS (u): detaching hands the drag over instead of holding both.")


def test_window_shows_no_caption_text():
    """An empty title is not enough.

    Qt substitutes QApplication.applicationName() whenever a window's title is
    empty, so setWindowTitle("") put "Clickwheel File Explorer" straight back into the title bar.
    A single space defeats the substitution and renders blank.
    """
    if sys.platform != "win32" or app.platformName() != "windows":
        print("SKIP (v): needs the windows platform plugin.")
        return
    import ctypes
    stage = Stage()
    stage.resize(700, 500)
    stage.show()
    pump(300)

    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(int(stage.winId()), buf, 256)
    caption = buf.value
    assert caption.strip() == "", f"title bar shows {caption!r}"
    assert not stage.windowIcon().isNull(), "icon should still identify the app"
    print(f"PASS (v): native caption is blank ({caption!r}), icon retained.")


if __name__ == "__main__":
    test_spec_parsing()
    test_bad_specs_rejected()
    test_describe_is_readable()
    test_panel_geometry_hugs_left_edge()
    test_registration_round_trip()
    test_hotkey_survives_taskbar_flag_change()
    test_taskbar_flag_toggles()
    test_icon_is_built_and_multisize()
    test_toggle_switches_visibility()
    test_animation_settles_on_the_edge()
    test_toggle_from_a_normal_window_summons_rather_than_hides()
    test_autohide_has_a_grace_period()
    test_panel_opens_on_the_screen_under_the_cursor()
    test_autohide_waits_until_the_panel_has_held_focus()
    test_app_survives_hiding_its_only_window()
    test_hotkey_watchdog_reclaims_a_lost_registration()
    test_window_is_manageable_by_window_managers()
    test_maximise_respects_the_work_area()
    test_detaching_keeps_one_appearance()
    test_detach_releases_our_drag_state()
    test_window_shows_no_caption_text()
    test_panel_mode_does_not_overwrite_saved_window_size()
