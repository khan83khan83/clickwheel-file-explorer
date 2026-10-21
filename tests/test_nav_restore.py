"""The panel reopens where it was left: folder trail, highlighted row and scroll
position survive a restart, via state.json."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
TMP = Path(tempfile.mkdtemp(prefix="ipodpdf_nav_"))
os.environ["APPDATA"] = str(TMP / "appdata")          # never touch the real state
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import config                                           # noqa: E402
from app.application import Stage                                # noqa: E402
from app.navigation import ScreenStack                           # noqa: E402
from main import build_root_menu                                 # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

LIB = TMP / "lib"


def make_library():
    for d in ("alpha", "beta/inner", "gamma"):
        (LIB / d).mkdir(parents=True)
    for i in range(30):                      # long enough that the list scrolls
        (LIB / "beta" / "inner" / f"doc{i:02d}.pdf").write_bytes(b"%PDF-1.4\n")
    (LIB / "alpha" / "a.pdf").write_bytes(b"%PDF-1.4\n")


def fresh():
    config.CURRENT.clear()
    config.CURRENT["library_root"] = str(LIB)
    stage = Stage()
    stage.resize(420, 600)
    stack = ScreenStack(stage)
    stage.set_stack(stack)
    stack.root_factory = lambda: build_root_menu(stack)
    stack.push(build_root_menu(stack))
    return stage, stack


def labels(screen):
    return [r.label for r in screen.rows]


def test_round_trip():
    make_library()
    stage, stack = fresh()

    root = stack.top
    root.sel = labels(root).index("beta")
    root.on_left_click(0, 0)                                # into beta
    beta = stack.top
    beta.sel = labels(beta).index("inner")
    beta.on_left_click(0, 0)                                # into beta/inner
    inner = stack.top
    inner.on_wheel(20)                                      # scroll down the list
    want_sel, want_top = inner.sel, inner.top
    assert want_top > 0, "test needs a scrolled list"
    assert stack.depth == 3

    stage.save_nav()                                        # what hiding does

    # "Restart": brand-new stage and stack, state read back from disk.
    stage2, stack2 = fresh()
    assert stack2.depth == 1
    assert stack2.restore(config.load_state().get("nav")), "restore refused"

    assert stack2.depth == 3, stack2.depth
    got = stack2.top
    assert Path(got.library_path) == LIB / "beta" / "inner", got.library_path
    assert got.sel == want_sel and got.top == want_top, (got.sel, got.top)
    # The root must keep its pinned actions, not become a bare listing.
    assert "Quit" in labels(stack2.screens[0]), labels(stack2.screens[0])
    print("PASS: trail, cursor, scroll and root actions survive a restart")


def test_vanished_folder_lands_on_ancestor():
    stage, stack = fresh()
    assert stack.restore(config.load_state().get("nav"))
    (LIB / "beta" / "inner").rename(LIB / "beta" / "renamed")
    stage2, stack2 = fresh()
    assert stack2.restore(config.load_state().get("nav"))
    assert stack2.depth == 2 and Path(stack2.top.library_path) == LIB / "beta"
    print("PASS: a deleted folder drops back to the nearest surviving parent")


def test_other_library_root_is_ignored():
    stage, stack = fresh()
    nav = [{"kind": "MenuScreen", "path": str(TMP / "elsewhere"), "cursor": 3,
            "top": 0}]
    assert not stack.restore(nav)
    assert stack.depth == 1
    assert not stack.restore(None) and not stack.restore([{"bad": 1}])
    print("PASS: a snapshot from another library root, or garbage, is ignored")


if __name__ == "__main__":
    test_round_trip()
    test_vanished_folder_lands_on_ancestor()
    test_other_library_root_is_ignored()
