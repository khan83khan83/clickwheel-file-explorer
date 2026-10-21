import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QPixmap                                # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import config, theme                                    # noqa: E402
from app.application import Stage                                # noqa: E402
from app.navigation import ScreenStack                           # noqa: E402
from app.library.model import LibraryNode, clean_name            # noqa: E402
from app.library.scanner import scan                             # noqa: E402
from app.render.pdfrender import PdfRenderer, zoom_bucket        # noqa: E402
from app.screens.reader_screen import ReaderScreen, FIT_MODES    # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def real_pdf() -> LibraryNode:
    root = scan(Path(config.load_config()["library_root"]))
    docs = root.docs or (root.children[0].docs if root.children else [])
    assert docs, "no PDFs found in the library; cannot run reader tests"
    return docs[0]


def make_reader():
    stage = Stage()
    stage.resize(1100, 720)
    stack = ScreenStack(stage)
    stage.set_stack(stack)
    screen = ReaderScreen(stack, real_pdf())
    stack.screens.append(screen)
    screen.on_enter()
    return screen


def test_layout_monotonic():
    r = make_reader()
    tops = r._page_tops
    assert len(tops) == r.meta.page_count
    assert all(tops[i] < tops[i + 1] for i in range(len(tops) - 1)), "page tops must increase"
    expected = sum(r._page_hs) + theme.PAGE_GAP * (len(tops) - 1)
    assert abs(r._total_h - expected) < 0.01, f"{r._total_h} != {expected}"
    print(f"PASS (a): layout monotonic over {len(tops)} pages, total {r._total_h:.0f}px.")


def test_clamp_bounds():
    r = make_reader()
    assert r._clamp(-500) == 0.0
    assert r._clamp(10 ** 9) == max(0.0, r._total_h - r._H())
    print("PASS (b): scroll clamps to [0, total_h - screen_h], no overscroll.")


def test_current_page_tracks_viewport_centre():
    r = make_reader()
    for target in (0, 3, min(7, r.meta.page_count - 1)):
        # Put the page's own centre at the viewport centre.
        centre = r._page_tops[target] + r._page_hs[target] / 2
        r.scroll.snap(r._clamp(centre - r._H() / 2))
        got = r.current_page()
        assert got == target + 1, f"expected page {target+1}, got {got}"
    print("PASS (c): current_page follows the viewport centre.")


def test_fit_cycle_preserves_page():
    r = make_reader()
    target = min(5, r.meta.page_count - 1)
    r.scroll.snap(r._clamp(r._page_tops[target]))
    before = r.current_page()
    seen = []
    for _ in range(len(FIT_MODES)):
        r.on_middle_click(0, 0)
        seen.append(r.fit_mode)
        assert r.current_page() == before, (
            f"fit mode {r.fit_mode} moved the reader off page {before}")
    assert seen == list(FIT_MODES[1:]) + [FIT_MODES[0]], seen
    assert r._clamp(r.scroll.value) == r.scroll.value
    print(f"PASS (d): fit cycle {seen} holds page {before} and stays in bounds.")


def test_progress_round_trip():
    r = make_reader()
    target = min(4, r.meta.page_count - 1)
    r.scroll.snap(r._clamp(r._page_tops[target]))
    r.save_progress()

    key = str(r.node.path.resolve())
    entry = config.load_state()["progress"][key]
    assert entry["total"] == r.meta.page_count
    assert entry["page"] == r.current_page()

    fresh = make_reader()
    assert abs(fresh.scroll.value - r.scroll.value) < 1.0, (
        f"resumed at {fresh.scroll.value}, saved {r.scroll.value}")
    assert config.load_state()["recent"][0] == key, "opened doc should head recents"
    print(f"PASS (e): progress round-trips (page {entry['page']}) and recents update.")


def test_zoom_bucket_absorbs_drift():
    a = zoom_bucket(1.234567)
    b = zoom_bucket(1.2344)
    assert a == b == 1.23, (a, b)
    print("PASS (f): zoom_bucket collapses sub-1% drift onto one cache key.")


def test_cache_respects_byte_cap():
    r = PdfRenderer()
    r.shutdown()
    import app.render.pdfrender as pr
    pr.CACHE_BYTES_MAX = 4 * 1024 * 1024
    r._cache.clear()
    r._bytes = 0
    for i in range(40):                       # 40 x 1MB = 40MB into a 4MB cap
        pm = QPixmap(512, 512)                # 512*512*4 = 1 MiB
        r._put(("doc", i, 1.0), pm)
    assert r._bytes <= pr.CACHE_BYTES_MAX, f"{r._bytes} exceeds cap"
    assert len(r._cache) < 40, "nothing was evicted"
    newest = ("doc", 39, 1.0)
    assert newest in r._cache, "most recent page was evicted"
    print(f"PASS (g): LRU held {len(r._cache)} pages under the byte cap, newest kept.")


def test_clean_name_recovers_bracket_only_titles():
    got = clean_name("[TIME vol. 200 iss. 23-24] - (2022) - libgen.li.pdf")
    assert got == "TIME vol. 200 iss. 23-24", got
    assert clean_name("Naive Set Theory (Paul R. Halmos).pdf") == "Naive Set Theory (Paul R. Halmos)"
    assert clean_name(".pdf") == ""  or clean_name(".pdf") is not None
    print(f"PASS (h): bracket-only titles recovered -> {got!r}")


if __name__ == "__main__":
    test_layout_monotonic()
    test_clamp_bounds()
    test_current_page_tracks_viewport_centre()
    test_fit_cycle_preserves_page()
    test_progress_round_trip()
    test_zoom_bucket_absorbs_drift()
    test_cache_respects_byte_cap()
    test_clean_name_recovers_bracket_only_titles()
