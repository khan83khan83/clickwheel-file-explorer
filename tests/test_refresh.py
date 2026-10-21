import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop                            # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import config                                           # noqa: E402
from app.application import Stage                                # noqa: E402
from app.library.service import LibraryService                   # noqa: E402
from app.navigation import ScreenStack                           # noqa: E402
from app.screens.menu_screen import MenuRow, MenuScreen          # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def pump(ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        time.sleep(0.01)


def sample_pdf() -> Path:
    root = Path(config.load_config()["library_root"])
    for p in root.rglob("*.pdf"):
        return p
    raise AssertionError("no sample PDF available")


def build_root(stack, path: Path):
    from app.library.scanner import list_dir
    screen = MenuScreen.from_node(stack, list_dir(path))
    screen.rows.append(MenuRow("Quit", "action", None, action="exit"))
    return screen


def make_env(tmp: Path):
    stage = Stage()
    stage.resize(1100, 720)
    stack = ScreenStack(stage)
    stage.set_stack(stack)

    lib = LibraryService(tmp)
    stack.library = lib
    stack.root_factory = lambda: build_root(stack, tmp)
    lib.changed.connect(stack.relist)
    stack.push(build_root(stack, tmp))
    return stage, stack, lib


def count_files(stack) -> int:
    """Files listed on the root screen, however deep the user has gone."""
    root = stack.screens[0]
    return sum(1 for r in root.rows if r.kind == "doc")


def count_folders(stack) -> int:
    root = stack.screens[0]
    return sum(1 for r in root.rows if r.kind == "folder")


def test_detects_added_and_removed_files():
    src = sample_pdf()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "Papers").mkdir()
        shutil.copy(src, tmp / "one.pdf")

        _stage, stack, lib = make_env(tmp)
        assert count_files(stack) == 1, count_files(stack)
        assert count_folders(stack) == 1, count_folders(stack)

        shutil.copy(src, tmp / "two.pdf")
        pump(2500)
        assert count_files(stack) == 2, (
            f"added file not picked up: {count_files(stack)}")
        print("PASS (a): a file added on disk appears without restarting.")

        (tmp / "two.pdf").unlink()
        pump(2500)
        assert count_files(stack) == 1, (
            f"deleted file still listed: {count_files(stack)}")
        print("PASS (b): a file deleted on disk disappears without restarting.")

        # Non-PDF files must show up too — this is a file browser now.
        (tmp / "notes.txt").write_text("hello", encoding="utf-8")
        (tmp / "clip.mp4").write_bytes(b"\x00" * 32)
        (tmp / "Notes").mkdir()
        pump(2500)
        labels = {r.label for r in stack.screens[0].rows}
        # Only ".pdf" is stripped from display names; other extensions stay,
        # because in a general browser the extension is information.
        assert "notes.txt" in labels and "clip.mp4" in labels, labels
        assert "one" in labels, f"a .pdf should lose its extension: {labels}"
        assert count_folders(stack) == 2, count_folders(stack)
        print(f"PASS (c): non-PDF files and a new folder both appear "
              f"({count_folders(stack)} folders, {count_files(stack)} files).")


def test_stack_survives_rescan_and_keeps_position():
    src = sample_pdf()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for folder in ("Alpha", "Beta", "Gamma"):
            (tmp / folder).mkdir()
            shutil.copy(src, tmp / folder / "doc.pdf")

        _stage, stack, lib = make_env(tmp)

        # Descend into the first folder, then move the cursor.
        stack.top.sel = 0
        stack.top.on_left_click(0, 0)
        assert stack.depth == 2, stack.depth
        deep_path = stack.top.library_path
        assert deep_path == tmp / "Alpha", deep_path
        stack.screens[0].sel = 2

        lib.refresh()
        pump(2500)

        assert stack.depth == 2, f"stack collapsed after refresh: {stack.depth}"
        assert stack.top.library_path == deep_path, "landed on a different folder"
        assert stack.screens[0].sel == 2, f"cursor moved: {stack.screens[0].sel}"
        print("PASS (d): refresh preserves stack depth, location and cursor.")


def test_vanished_folder_pops_to_ancestor():
    src = sample_pdf()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "Doomed").mkdir()
        shutil.copy(src, tmp / "Doomed" / "doc.pdf")
        (tmp / "Keep").mkdir()
        shutil.copy(src, tmp / "Keep" / "doc.pdf")

        _stage, stack, lib = make_env(tmp)
        stack.top.sel = 0                      # "Doomed"
        stack.top.on_left_click(0, 0)
        deep = stack.depth
        assert deep == 2, deep
        assert stack.top.library_path == tmp / "Doomed", stack.top.library_path

        # Let the cover workers finish: a PDF is briefly locked while its cover
        # is being rendered, which is exactly what blocks deletion on Windows.
        pump(2500)
        shutil.rmtree(tmp / "Doomed")
        pump(3000)

        assert stack.depth < deep, "should have popped off the deleted folder"
        assert stack.top is not None
        print(f"PASS (e): deleting the open folder pops to an ancestor "
              f"(depth {deep} -> {stack.depth}) instead of showing a dead screen.")


def test_only_open_directories_are_watched():
    """The Desktop holds ~10k files; watching the whole tree is not viable."""
    src = sample_pdf()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name in ("A", "B", "C"):
            (tmp / name).mkdir()
            (tmp / name / "sub").mkdir()
            shutil.copy(src, tmp / name / "doc.pdf")

        _stage, stack, lib = make_env(tmp)
        watched = set(lib.watched())
        assert watched == {str(tmp)}, (
            f"only the open directory should be watched, got {watched}")

        stack.top.sel = 0
        stack.top.on_left_click(0, 0)
        watched = set(lib.watched())
        assert watched == {str(tmp), str(tmp / "A")}, watched

        stack.top.on_right_click(0, 0)
        pump(300)
        assert set(lib.watched()) == {str(tmp)}, lib.watched()
        print("PASS (f): watches follow the open path only — one per level, "
              "released on the way back.")


if __name__ == "__main__":
    test_detects_added_and_removed_files()
    test_only_open_directories_are_watched()
    test_stack_survives_rescan_and_keeps_position()
    test_vanished_folder_pops_to_ancestor()
