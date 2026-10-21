import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from app import config
from app import hotkey as hotkey_mod
from app.application import Stage
from app.library.service import LibraryService
from app.navigation import ScreenStack
from app.screens.menu_screen import MenuRow, MenuScreen


def build_root_menu(stack, root_path=None):
    """The first page IS the root folder: its subfolders and its files, plus a
    few app actions pinned at the end."""
    from app.library.scanner import list_dir
    path = Path(root_path or config.get("library_root"))
    node = list_dir(path)

    screen = MenuScreen.from_node(stack, node)
    screen._title = path.name or str(path)
    screen.rows.extend([
        MenuRow("Refresh", "action", None, action="refresh"),
        MenuRow("Change Folder…", "action", None, action="library"),
        MenuRow("Appearance", "action", None, action="theme"),
        MenuRow("Quit", "action", None, action="exit"),
    ])
    return screen


SCREEN_USE = 0.90       # never open larger than this share of the usable desktop


def install_logging() -> Path:
    """Make the app diagnosable when launched with pythonw.exe.

    pythonw sets sys.stdout and sys.stderr to None, so every print vanishes and
    an unhandled exception dies in total silence — the process simply
    disappears with no trace anywhere. Point both at a log file and record
    faults and unhandled exceptions there.
    """
    import datetime
    import faulthandler

    log_dir = config.get_localappdata_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    stream = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    stream.write(f"\n=== started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")

    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream

    faulthandler.enable(stream)          # catches hard crashes too

    def hook(exc_type, exc, tb):
        import traceback
        stream.write(f"\n--- unhandled {datetime.datetime.now():%H:%M:%S} ---\n")
        traceback.print_exception(exc_type, exc, tb, file=stream)
        stream.flush()

    sys.excepthook = hook
    return log_path


def autostart_enabled() -> bool:
    from app import autostart
    return autostart.is_enabled()


def set_autostart(enabled: bool) -> None:
    """Start with Windows. Only ever called from the tray menu, by the user.

    A shortcut in the user's own Startup folder rather than a registry Run
    entry: it appears in Task Manager's Startup tab like any other app, and
    undoing it is deleting one file. It launches with --background, so signing
    in leaves the app resident and silent rather than throwing a window up.
    """
    from app import autostart
    ok, msg = autostart.set_enabled(enabled, Path(__file__).resolve().parent,
                                    asset("icons/app.ico"))
    print(f"autostart: {msg}", flush=True)


def build_tray(app, stage):
    """A tray icon, so the app has a visible existence.

    With quitOnLastWindowClosed disabled the app outlives its window, which
    means it needs somewhere to live while hidden and an explicit way to quit.
    It also answers the question the user could not previously answer: is this
    thing even running?
    """
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon

    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    icon_path = asset("icons/app.ico")
    icon = QIcon(str(icon_path)) if icon_path.exists() else app.windowIcon()
    tray = QSystemTrayIcon(icon, app)

    spec = config.get("hotkey") or "ctrl+e"
    from app import hotkey as hotkey_mod
    tray.setToolTip(f"{config.APP_NAME} — {hotkey_mod.describe(spec)}")

    menu = QMenu()
    menu.addAction("Open panel", stage.show_panel)
    menu.addAction("Open window", lambda: (stage.set_taskbar_visible(True),
                                           stage.show(), stage.raise_(),
                                           stage.activateWindow()))
    menu.addSeparator()

    auto = menu.addAction("Start with Windows")
    auto.setCheckable(True)
    auto.setChecked(autostart_enabled())
    auto.toggled.connect(set_autostart)

    menu.addSeparator()
    menu.addAction("Quit", app.quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: stage.toggle_panel()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    return tray, menu        # both must be kept alive


def claim_single_instance() -> bool:
    """True if this is the only instance; False if one is already running.

    A global hotkey can only belong to one process. Without this, every launch
    leaves another copy behind and whichever one happened to start first keeps
    Ctrl+E — so the key appears dead because it is toggling a window you are
    not looking at.
    """
    if sys.platform != "win32":
        return True
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ERROR_ALREADY_EXISTS = 183
    # Held for the life of the process; Windows releases it automatically.
    global _INSTANCE_MUTEX
    _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "ClickwheelFileExplorer.SingleInstance")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


_INSTANCE_MUTEX = None


def asset(rel: str) -> Path:
    """Resolve a bundled asset, from source or from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / rel


def fit_window(area, saved: dict, min_w: int, min_h: int):
    """Choose a window rect that is guaranteed to fit on screen.

    A frameless window gets no help from the OS: nothing clamps an oversized
    saved geometry, and nothing pulls it back on-screen. A window taller than
    the desktop puts its own title strip above y=0, leaving no way to move or
    resize it with the mouse.

    Returns (x, y, w, h) in the screen's coordinates.
    """
    avail_w, avail_h = area.width(), area.height()

    w = int(saved.get("w") or 1100)
    h = int(saved.get("h") or 720)
    w = min(w, int(avail_w * SCREEN_USE))
    h = min(h, int(avail_h * SCREEN_USE))
    # Never below the minimum, but also never past the desktop itself.
    w = max(min(min_w, avail_w), w)
    h = max(min(min_h, avail_h), h)

    x, y = saved.get("x"), saved.get("y")
    if x is None or y is None:
        x = area.x() + (avail_w - w) // 2
        y = area.y() + (avail_h - h) // 2

    # Clamp so every edge stays reachable.
    x = max(area.x(), min(int(x), area.x() + avail_w - w))
    y = max(area.y(), min(int(y), area.y() + avail_h - h))
    return x, y, w, h


def main():
    moved = config.migrate_legacy_dirs()        # before the log file is opened
    log_path = install_logging()
    print(f"log: {log_path}")
    for line in moved:
        print(f"migrated: {line}")

    if not claim_single_instance():
        print("another instance is already running — exiting so it keeps the "
              "hotkey")
        return

    # Windows groups taskbar buttons by AppUserModelID. Without an explicit
    # one, the app inherits pythonw.exe's identity — which is why it showed
    # Python's icon, or none at all, instead of its own.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ClickwheelFileExplorer.Panel.1")
        except Exception as e:
            print(f"app id: {e}")

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)

    # THE reason the hotkey kept "breaking": this defaults to True, so hiding
    # the panel left zero visible windows and Qt shut the whole application
    # down — cleanly, with no crash, no traceback and nothing in the event log.
    # The process simply ceased to exist and every later keypress went nowhere.
    # A panel app must outlive its window.
    app.setQuitOnLastWindowClosed(False)

    icon_path = asset("icons/app.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config.init()

    stage = Stage()
    stack = ScreenStack(stage)
    stage.set_stack(stack)

    library = LibraryService(Path(config.get("library_root")))
    stack.library = library
    stack.root_factory = lambda: build_root_menu(stack)
    library.changed.connect(stack.relist)

    stack.push(build_root_menu(stack))

    area = app.primaryScreen().availableGeometry()
    x, y, w, h = fit_window(area, config.get("window") or {},
                            stage.minimumWidth(), stage.minimumHeight())
    stage.resize(w, h)
    stage.move(x, y)

    # Reopen where the user left off. After the resize, so the saved scroll
    # position is checked against the real number of visible rows.
    try:
        stack.restore(config.load_state().get("nav"))
    except Exception as e:           # a bad saved state must never block startup
        print(f"could not restore navigation: {e}", flush=True)
    app.aboutToQuit.connect(stage.save_nav)

    stage._panel_autohide = bool(config.get("panel_autohide", True))

    # --background: started by the Startup shortcut. Stay resident and silent,
    # with only the tray icon and the hotkey live, until summoned.
    background = "--background" in sys.argv
    if background:
        # Take the Qt.Tool flag now rather than on the first summon. Switching
        # it destroys and recreates the native window, which stalls Qt's
        # animation driver for about half a second — paid here, at launch,
        # instead of making the first Ctrl+E feel broken.
        stage.set_taskbar_visible(False)
        print("started in the background; waiting for the hotkey", flush=True)
    else:
        stage.show()
        stage.raise_()
        stage.activateWindow()

    tray = build_tray(app, stage)        # keep the reference alive
    if tray is None:
        print("no system tray available; the app will still run", flush=True)
    elif background:
        # Starting silently is the point, but "silent" and "did not start" look
        # identical. Say so once, so signing in gives visible confirmation.
        spec_label = hotkey_mod.describe(config.get("hotkey") or "ctrl+e")
        tray[0].showMessage(
            f"{config.APP_NAME} is running",
            f"Press {spec_label} to open the panel.",
            tray[0].MessageIcon.Information, 5000)

    spec = config.get("hotkey") or "ctrl+e"
    err = stage.install_hotkey(spec)
    if err:
        print(f"hotkey: {err}\n"
              f"        the app still runs; change \"hotkey\" in "
              f"{config.CONFIG_PATH} to a free combination.", flush=True)
    else:
        print(f"hotkey: {hotkey_mod.describe(spec)} summons and dismisses the "
              f"side panel.", flush=True)

    # Carry an existing start-with-Windows choice over to the new name, and to
    # the packaged exe. Shells out to PowerShell, so it runs after startup
    # rather than delaying the hotkey.
    from PySide6.QtCore import QTimer

    def reconcile_autostart():
        from app import autostart
        msg = autostart.reconcile(Path(__file__).resolve().parent,
                                  asset("icons/app.ico"))
        if msg:
            print(msg, flush=True)
    QTimer.singleShot(3000, reconcile_autostart)

    if "--diag" in sys.argv:
        print(f"visible={stage.isVisible()} geometry={stage.geometry()} "
              f"winId={int(stage.winId())} screen={stage.screen().name()}",
              flush=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
