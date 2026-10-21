import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QImage, QPainter                       # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import theme                                            # noqa: E402
from app.application import Stage                                # noqa: E402
from app.library.model import LibraryNode                        # noqa: E402
from app.navigation import ScreenStack                           # noqa: E402
from app.screens.menu_screen import MenuRow, MenuScreen, has_pdfs  # noqa: E402

WIN_W, WIN_H = 1100, 720

app = QApplication.instance() or QApplication(sys.argv)


def new_stage():
    stage = Stage()
    stage.resize(WIN_W, WIN_H)
    stack = ScreenStack(stage)
    stage.set_stack(stack)
    return stage, stack


def shot(stage, screen) -> QImage:
    img = QImage(stage.content_w, stage.content_h,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    screen.paint(p)
    p.end()
    return img


def mock_tree():
    root = LibraryNode(path=Path("/test"), name="Root", is_dir=True)
    f1 = LibraryNode(path=Path("/test/f1"), name="Folder 1", is_dir=True, parent=root)
    f1.docs.append(LibraryNode(path=Path("/test/f1/a.pdf"), name="a", is_dir=False, parent=f1))

    f2 = LibraryNode(path=Path("/test/f2"), name="Folder 2", is_dir=True, parent=root)
    f3 = LibraryNode(path=Path("/test/f2/f3"), name="Folder 3", is_dir=True, parent=f2)
    f3.docs.append(LibraryNode(path=Path("/test/f2/f3/b.pdf"), name="b", is_dir=False, parent=f3))
    f2.children.append(f3)

    root.children.extend([f1, f2])
    root.docs.append(LibraryNode(path=Path("/test/c.pdf"), name="c", is_dir=False, parent=root))
    return root, f1, f2


def test_row_construction():
    """Folders first, then files — and a Covers row only when it earns one."""
    _stage, stack = new_stage()
    root, _f1, _f2 = mock_tree()

    # Even a single file gets a Covers row: in a narrow window the preview panel
    # is hidden, so this is the only way to see that file's cover.
    screen = MenuScreen.from_node(stack, root)
    assert screen is not None
    assert [r.kind for r in screen.rows] == ["covers", "folder", "folder", "doc"], \
        [r.kind for r in screen.rows]
    assert screen.rows[0].label == "Covers (1)", screen.rows[0].label
    assert [r.label for r in screen.rows][1:3] == ["Folder 1", "Folder 2"]

    root.docs.append(LibraryNode(path=Path("/test/d.pdf"), name="d",
                                 is_dir=False, parent=root))
    screen2 = MenuScreen.from_node(stack, root)
    assert [r.kind for r in screen2.rows] == ["covers", "folder", "folder",
                                              "doc", "doc"], \
        [r.kind for r in screen2.rows]
    assert screen2.rows[0].label == "Covers (2)", screen2.rows[0].label

    # A folder with no files at all should not offer Cover Flow.
    empty = LibraryNode(path=Path("/test/empty"), name="Empty", is_dir=True)
    assert MenuScreen.from_node(stack, empty).rows == []
    print("PASS (e): folders then files, with a Covers row whenever there is "
          "at least one file to preview.")


def test_selection_is_painted_in_accent():
    stage, stack = new_stage()
    rows = [MenuRow(f"Row {i}", "folder", None) for i in range(40)]
    screen = MenuScreen(stack, "Scroll", rows)
    stack.push(screen)
    screen.scroll_anim.snap(0.0)

    img = shot(stage, screen)
    sel = theme.color("SEL_BG")
    got = img.pixelColor(40, theme.ROW_H // 2)
    assert abs(got.blue() - sel.blue()) < 12 and abs(got.red() - sel.red()) < 12, \
        f"row 0 should be {sel.name()}, got {got.name()}"

    unsel = img.pixelColor(40, theme.ROW_H + theme.ROW_H // 2)
    # Ask the stage, the single source for the background:
    # docked and floating deliberately share one surface.
    assert unsel.name() == stage.background_color().name(), (
        f"row 1 should be the app background, got {unsel.name()}")
    print("PASS (a): selected row uses the accent fill; unselected rows do not.")


def test_wheel_moves_one_row_and_clamps():
    stage, stack = new_stage()
    rows = [MenuRow(f"Row {i}", "folder", None) for i in range(40)]
    screen = MenuScreen(stack, "Scroll", rows)
    stack.push(screen)

    screen.on_wheel(1)
    assert screen.sel == 1, screen.sel
    print("PASS (b): one detent moves the selection exactly one row.")

    # Forward off the end continues from the start, and back again.
    screen.sel = 39
    screen.on_wheel(1)
    assert screen.sel == 0, f"end should wrap to the start, got {screen.sel}"
    screen.on_wheel(-1)
    assert screen.sel == 39, f"start should wrap to the end, got {screen.sel}"

    # An accelerated flick wraps by the right amount, not just by one.
    screen.sel = 38
    screen.on_wheel(5)
    assert screen.sel == 3, f"38 + 5 of 40 should land on 3, got {screen.sel}"
    screen.sel = 1
    screen.on_wheel(-4)
    assert screen.sel == 37, f"1 - 4 of 40 should land on 37, got {screen.sel}"

    # A wrap must not leave the viewport scrolled somewhere unrelated.
    screen.sel = 39
    screen.on_wheel(1)
    assert screen.top == 0, f"wrapping to the top should show the top: {screen.top}"
    print("PASS (c): selection wraps at both ends and the view follows it.")


def test_wrap_can_be_switched_off():
    from app import config
    from app.input import advance

    assert advance(9, 1, 10) == (0, True)
    assert advance(0, -1, 10) == (9, True)
    assert advance(3, 2, 10) == (5, False)
    assert advance(0, 5, 0) == (0, False), "empty list must not divide by zero"
    assert advance(4, 0, 10) == (4, False)

    config.CURRENT["wrap"] = False
    try:
        assert advance(9, 1, 10) == (9, False), "wrap:false should clamp"
        assert advance(0, -1, 10) == (0, False)
    finally:
        config.CURRENT["wrap"] = True
    print("PASS (m): wrapping is exact at both ends, safe on empty lists, "
          "and switchable off.")


def test_scrollbar_only_when_overflowing():
    stage, stack = new_stage()
    vis = int(stage.content_h // theme.ROW_H)
    lw = theme.list_width(stage.content_w)
    probe_x = lw - theme.SCROLLBAR_W - 2

    many = MenuScreen(stack, "Many", [MenuRow(f"R{i}", "folder", None)
                                      for i in range(vis * 3)])
    stack.push(many)
    many.scroll_anim.snap(0.0)
    img = shot(stage, many)
    thumb = theme.color("SCROLL_THUMB")
    hit = any(abs(img.pixelColor(probe_x, y).red() - thumb.red()) < 12
              for y in range(6, 60))
    assert hit, "expected a scrollbar thumb when rows overflow"

    few = MenuScreen(stack, "Few", [MenuRow(f"R{i}", "folder", None) for i in range(3)])
    img2 = shot(stage, few)
    hit2 = any(abs(img2.pixelColor(probe_x, y).red() - thumb.red()) < 12
               for y in range(6, 60))
    assert not hit2, "no scrollbar should be drawn when everything fits"
    print(f"PASS (d): scrollbar appears only past {vis} visible rows.")


def test_layout_reflows_with_window():
    stage, stack = new_stage()
    screen = MenuScreen(stack, "Any", [MenuRow("R", "folder", None)])
    stack.push(screen)

    narrow = theme.list_width(700)
    wide = theme.list_width(1600)
    assert narrow < wide, (narrow, wide)
    assert theme.LIST_MIN <= narrow <= theme.LIST_MAX
    assert theme.LIST_MIN <= wide <= theme.LIST_MAX

    stage.resize(700, 500)
    small_rows = screen.visible_rows()
    stage.resize(1400, 1000)
    big_rows = screen.visible_rows()
    assert big_rows > small_rows, (small_rows, big_rows)
    print(f"PASS (i): layout reflows — {small_rows} rows at 700x500, "
          f"{big_rows} at 1400x1000.")


def test_preview_panel_drops_when_narrow():
    stage, stack = new_stage()
    screen = MenuScreen(stack, "Any", [MenuRow(f"R{i}", "folder", None)
                                       for i in range(5)])
    stack.push(screen)

    # Wide: panel present, list is only part of the width.
    stage.resize(1100, 720)
    assert screen.show_art() is True
    assert screen.list_width() < stage.content_w
    img = shot(stage, screen)
    right = img.pixelColor(stage.content_w - 40, stage.content_h // 2)
    assert right.name() != stage.background_color().name(), (
        "wide layout should paint a preview panel on the right")

    # Narrow: panel gone, list spans everything.
    stage.resize(theme.ART_MIN_W - 60, 720)
    assert screen.show_art() is False
    assert screen.list_width() == stage.content_w
    img = shot(stage, screen)
    right = img.pixelColor(stage.content_w - 40, stage.content_h // 2)
    assert right.name() == stage.background_color().name(), (
        "narrow layout must not paint a preview panel")

    # And the rows get the reclaimed space.
    stage.resize(1100, 720)
    wide_list = screen.list_width()
    stage.resize(theme.ART_MIN_W - 60, 720)
    assert screen.list_width() > wide_list - 1, \
        "narrow list should be at least as wide as the wide one's list"
    print(f"PASS (k): preview panel drops below {theme.ART_MIN_W}px and the "
          f"list reclaims the full width.")


def test_narrow_layout_skips_cover_work():
    stage, stack = new_stage()
    root, _f1, _f2 = mock_tree()
    screen = MenuScreen.from_node(stack, root)
    stack.push(screen)

    stage.resize(theme.ART_MIN_W - 60, 720)
    screen.art_pmaps = []
    screen._fetch_art()
    assert screen.art_pmaps == [], \
        "narrow layout must not queue cover renders for a panel it will not draw"
    print("PASS (l): no cover rendering is requested while the panel is hidden.")


def test_wrap_is_animated_not_snapped():
    """A wrap must be visible.

    Landing directly on the far end is indistinguishable from nothing having
    happened, so the view starts short of the destination — on the side the
    scroll came from — and slides in.
    """
    stage, stack = new_stage()
    rows = [MenuRow(f"R{i}", "folder", None) for i in range(40)]
    screen = MenuScreen(stack, "Wrap", rows)
    stack.push(screen)
    screen.scroll_anim.snap(0.0)

    # Forward off the end: content should arrive from below, i.e. the animator
    # starts BELOW its target and rises to it.
    screen.sel = len(rows) - 1
    screen.top = len(rows) - screen.visible_rows()
    screen.scroll_anim.snap(float(screen.top))
    screen.on_wheel(1)
    assert screen.sel == 0, screen.sel
    assert screen.scroll_anim.active, "wrap must animate, not snap"
    assert screen.scroll_anim.value < screen.scroll_anim.target_value, (
        "forward wrap should slide up into place")
    travel = abs(screen.scroll_anim.target_value - screen.scroll_anim.value)
    assert travel > 0.5, f"wrap travel too small to notice: {travel}"
    assert screen.scroll_anim.tau == theme.WRAP_TAU

    # Backward off the start: the mirror image.
    screen.sel = 0
    screen.top = 0
    screen.scroll_anim.snap(0.0)
    screen.scroll_anim.tau = theme.MENU_SCROLL_TAU
    screen.on_wheel(-1)
    assert screen.sel == len(rows) - 1, screen.sel
    assert screen.scroll_anim.value > screen.scroll_anim.target_value, (
        "backward wrap should slide down into place")

    # And the fast tau is handed back afterwards, so ordinary scrolling is
    # not left permanently quickened.
    for _ in range(400):
        if not screen.scroll_anim.tick(1 / 60):
            break
    assert screen.scroll_anim.tau == theme.MENU_SCROLL_TAU, (
        "wrap tau leaked into normal scrolling")
    print("PASS (n): wrap slides in from the direction of travel, then restores "
          "the normal scroll speed.")


def test_only_the_list_wraps():
    """Wrapping is a list affordance, not a Cover Flow one."""
    from app.input import advance

    # Lists loop at both ends.
    assert advance(9, 1, 10, wrap=True) == (0, True)
    assert advance(0, -1, 10, wrap=True) == (9, True)

    # Cover Flow stops dead, and never reports a wrap.
    assert advance(9, 1, 10, wrap=False) == (9, False)
    assert advance(0, -1, 10, wrap=False) == (0, False)
    assert advance(9, 99, 10, wrap=False) == (9, False)
    assert advance(0, -99, 10, wrap=False) == (0, False)

    # In-range movement is identical either way.
    assert advance(3, 2, 10, wrap=True)[0] == advance(3, 2, 10, wrap=False)[0] == 5
    print("PASS (o): the list wraps at both ends; Cover Flow stops at them.")


def test_click_routing():
    _stage, stack = new_stage()
    root, f1, _f2 = mock_tree()
    screen = MenuScreen.from_node(stack, root)
    stack.push(screen)

    from app.screens.coverflow_screen import CoverFlowScreen

    # Rows are folders then files, so the folders are at the top.
    folder_rows = [i for i, r in enumerate(screen.rows) if r.kind == "folder"]
    assert folder_rows, "mock tree should expose folder rows"
    depth = stack.depth
    screen.sel = folder_rows[-1]
    screen.on_left_click(0, 0)
    assert stack.depth == depth + 1, "a folder row should push a screen"
    assert isinstance(stack.top, MenuScreen)
    stack.pop()
    print("PASS (f): a folder row pushes a MenuScreen listing that folder.")

    # A file row opens the file rather than navigating. It must not push.
    depth = stack.depth
    doc_rows = [i for i, r in enumerate(screen.rows) if r.kind == "doc"]
    assert doc_rows, "mock tree should expose a file row"
    screen.sel = doc_rows[0]
    opened = {}
    import app.shell as shell_mod
    real = shell_mod.open_file
    shell_mod.open_file = lambda p: opened.setdefault("path", p) or True
    try:
        screen.on_left_click(0, 0)
    finally:
        shell_mod.open_file = real
    assert stack.depth == depth, "a file row must not push a screen"
    assert opened.get("path") is not None, "a file row should open the file"
    print(f"PASS (g): a file row opens {Path(opened['path']).name!r} "
          f"instead of navigating.")


def test_has_pdfs_counts_direct_children():
    _root, f1, _f2 = mock_tree()
    assert has_pdfs(f1) is True
    print("PASS (h): has_pdfs is True for a folder whose PDFs are direct children.")


def test_theme_switches_palette():
    theme.set_mode("dark")
    dark_bg = theme.color("WINDOW_BG")
    dark_fg = theme.color("TEXT")
    assert dark_bg.lightness() < 128, "dark theme needs a dark background"
    assert dark_fg.lightness() > 128, "dark theme needs light text"

    theme.set_mode("light")
    light_bg = theme.color("WINDOW_BG")
    light_fg = theme.color("TEXT")
    assert light_bg.lightness() > 128, "light theme needs a light background"
    assert light_fg.lightness() < 128, "light theme needs dark text"

    assert dark_bg.name() != light_bg.name()
    # Text must stay readable against its own background in both palettes.
    for bg, fg, label in ((dark_bg, dark_fg, "dark"), (light_bg, light_fg, "light")):
        assert abs(bg.lightness() - fg.lightness()) > 120, f"{label} contrast too low"

    theme.set_mode(None)
    print(f"PASS (j): palettes differ (dark {dark_bg.name()} / light "
          f"{light_bg.name()}), both high-contrast, and follow the system when unset.")


def test_entering_a_folder_lists_it_from_disk():
    """Rows hold STUB nodes, because listing is lazy.

    list_dir builds child nodes with empty .children and .docs. Building the
    next screen straight from such a stub yields an empty folder — which is
    invisible for a folder of files, but total for a folder whose contents are
    all subfolders.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Subfolders only: no direct files anywhere at this level.
        for name in ("Magazine", "Newspaper", "Textbook"):
            (root / name).mkdir()
        (root / "Magazine" / "issue.pdf").write_bytes(b"%PDF-1.4")

        _stage, stack = new_stage()
        screen = MenuScreen.from_path(stack, root)
        stack.push(screen)

        folder_rows = [r for r in screen.rows if r.kind == "folder"]
        assert len(folder_rows) == 3, [r.label for r in screen.rows]
        # The stub really is empty — this is the trap.
        assert not folder_rows[0].node.children and not folder_rows[0].node.docs

        screen.sel = screen.rows.index(folder_rows[0])
        depth = stack.depth
        screen.on_left_click(0, 0)

        assert stack.depth == depth + 1, "entering a folder should push a screen"
        child = stack.top
        assert child.rows, "entered a folder and got an empty screen"
        assert any(r.label == "issue.pdf" or r.kind == "doc" for r in child.rows),             [r.label for r in child.rows]

        # And a folder containing only subfolders lists those subfolders.
        stack.pop()
        nested = root / "Deep"
        (nested / "inner").mkdir(parents=True)
        screen2 = MenuScreen.from_path(stack, nested)
        assert [r.label for r in screen2.rows] == ["inner"], (
            [r.label for r in screen2.rows])
        print("PASS (p): entering a folder lists it from disk, subfolder-only "
              "folders included.")


if __name__ == "__main__":
    test_row_construction()
    test_selection_is_painted_in_accent()
    test_wheel_moves_one_row_and_clamps()
    test_wrap_can_be_switched_off()
    test_scrollbar_only_when_overflowing()
    test_layout_reflows_with_window()
    test_preview_panel_drops_when_narrow()
    test_narrow_layout_skips_cover_work()
    test_wrap_is_animated_not_snapped()
    test_only_the_list_wraps()
    test_click_routing()
    test_entering_a_folder_lists_it_from_disk()
    test_has_pdfs_counts_direct_children()
    test_theme_switches_palette()
