"""Render the app to PNG so it can be inspected without watching the screen.

    python tools/shoot.py menu
    python tools/shoot.py all           (menu + coverflow, both themes)

Renders the whole window including the custom title bar, at real resolution.
"""
import os
import sys
import time
from pathlib import Path

# NOT offscreen: on Windows the offscreen plugin has no font database, so every
# glyph renders as a tofu box and the shot misrepresents the app.
os.environ.setdefault("QT_QPA_PLATFORM",
                      "windows" if sys.platform == "win32" else "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QPoint                    # noqa: E402
from PySide6.QtGui import QImage                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import config, theme                                    # noqa: E402
from app.application import Stage                                # noqa: E402
from app.library.scanner import list_dir                         # noqa: E402
from app.navigation import ScreenStack                           # noqa: E402
from app.screens.coverflow_screen import CoverFlowScreen         # noqa: E402
from app.screens.menu_screen import MenuScreen                   # noqa: E402

WIN_W, WIN_H = 1100, 720
SHOTS = ROOT / "shots"


def pump(ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    app = QApplication.instance()
    while time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        time.sleep(0.01)


def render(stage: Stage, name: str) -> Path:
    img = QImage(stage.width(), stage.height(), QImage.Format.Format_ARGB32)
    img.fill(0)
    stage.render(img, QPoint(0, 0))
    SHOTS.mkdir(exist_ok=True)
    out = SHOTS / f"{name}.png"
    img.save(str(out))
    print(f"wrote {out}  ({img.width()}x{img.height()})  theme={theme.mode()}")
    return out


def build(stage):
    config.init()
    stack = ScreenStack(stage)
    stage.set_stack(stack)
    return stack, list_dir(Path(config.get("library_root")))


def shoot_menu(stage, suffix=""):
    import main as app_main
    stack, _root = build(stage)
    screen = app_main.build_root_menu(stack)
    stack.screens.append(screen)
    screen.on_enter()
    screen._fetch_art()
    pump(3500)
    screen._fetch_art()
    pump(600)
    render(stage, f"menu{suffix}")


def shoot_coverflow(stage, suffix=""):
    stack, root = build(stage)
    docs = root.docs or (root.children[0].docs if root.children else [])
    screen = CoverFlowScreen(stack, docs, start_index=min(3, len(docs) - 1))
    stack.screens.append(screen)
    screen.on_enter()
    pump(6000)
    screen._ensure_covers()
    pump(1200)
    render(stage, f"coverflow{suffix}")


def main():
    app = QApplication(sys.argv)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    for mode in ("dark", "light"):
        theme.set_mode(mode)
        suffix = "" if mode == "dark" else "_light"
        stage = Stage()
        stage.resize(WIN_W, WIN_H)
        stage.show()
        pump(300)
        if which in ("menu", "all"):
            shoot_menu(stage, suffix)
        if which in ("coverflow", "all"):
            shoot_coverflow(stage, suffix)
        stage.close()

    if which in ("menu", "narrow", "all"):
        theme.set_mode("dark")
        for w, h, tag in ((620, 700, "_narrow"), (240, 300, "_tiny")):
            stage = Stage()
            stage.resize(w, h)
            stage.show()
            pump(300)
            shoot_menu(stage, tag)
            stage.close()


if __name__ == "__main__":
    main()
