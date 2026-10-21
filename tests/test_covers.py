import os
import sys
import gc
import threading
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import QEventLoop

# Setup headless environment
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.library.document import Doc
from app.library.covers import CoverCache
from app.library.model import LibraryNode
from app.render.reflection import make_reflection
from PySide6.QtGui import QColor, QPixmap

def test_covers():
    app = QApplication(sys.argv)
    
    # Pick whatever PDF the library currently holds. Hardcoding a filename ties
    # the suite to one person's collection and breaks the moment a file is moved
    # or renamed — which is exactly what happened to the previous version.
    from app import config
    root = Path(config.load_config()["library_root"])
    candidates = sorted(root.rglob("*.pdf"))
    assert candidates, f"no PDFs under {root}; cannot run cover tests"
    pdf_path = candidates[0]


    # Test (a): Doc.render returns a non-null QImage of the expected width for a known zoom
    doc = Doc(pdf_path)
    w, h = doc.page_size(0)
    zoom = 2.0
    img = doc.render(0, zoom)
    assert not img.isNull(), "Doc.render returned a null image"
    assert type(img) is QImage, f"Expected QImage, got {type(img)}"
    
    expected_w = int(w * zoom)
    # PyMuPDF rendering might have off-by-one due to rounding in fitz.Matrix
    assert abs(img.width() - expected_w) <= 2, f"Expected width ~{expected_w}, got {img.width()}"
    print("PASS (a): Doc.render returns valid QImage of expected width.")
    
    # Test (f): The returned QImage stays valid after the source Pixmap goes out of scope
    doc.close()
    gc.collect()
    color = img.pixelColor(img.width() // 2, img.height() // 2)
    assert color.isValid(), "Image pixels became invalid after GC"
    print("PASS (f): QImage stays valid after GC (copied correctly).")
    
    # Test (c): Rendering same page twice from two threads with separate Doc instances both succeed
    results = []
    
    def worker_thread(idx):
        try:
            t_doc = Doc(pdf_path)
            t_img = t_doc.render(0, 1.0)
            if not t_img.isNull():
                results.append(idx)
            t_doc.close()
        except Exception as e:
            print(f"Thread {idx} failed: {e}")
            
    t1 = threading.Thread(target=worker_thread, args=(1,))
    t2 = threading.Thread(target=worker_thread, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(results) == 2, "Threaded render failed"
    print("PASS (c): Rendering same page from multiple threads with separate Doc instances works.")
    
    # Test (b) and (d): Cover cache request
    from app.library.covers import cache
    cache._mem.clear()
    
    stat = pdf_path.stat()
    node = LibraryNode(path=pdf_path, name=pdf_path.stem, is_dir=False, size=stat.st_size, mtime=stat.st_mtime)
    
    test_key = f"{node.cache_key}_200"
    test_disk_path = cache._cache_dir / f"{test_key}.jpg"
    if test_disk_path.exists():
        test_disk_path.unlink()
        
    loop = QEventLoop()
    emitted_key = None
    emitted_img = None
    
    def on_ready(k, i):
        nonlocal emitted_key, emitted_img
        emitted_key = k
        emitted_img = i
        loop.quit()
        
    cache.ready.connect(on_ready)
    
    pm = cache.request(node, 200)
    assert pm is None, "Expected None (async miss) on first request"
    
    # Second request shouldn't crash or re-enqueue
    pm2 = cache.request(node, 200)
    assert pm2 is None, "Expected None on second request while inflight"
    assert len(cache._inflight) == 1, "Expected only 1 inflight request for the same key"
    
    loop.exec() # wait for worker
    
    assert type(emitted_img) is QImage, f"Expected worker to emit QImage, emitted {type(emitted_img)}"
    print("PASS (b): Worker hands back QImage, not QPixmap.")
    
    cache_key = f"{node.cache_key}_200"
    disk_path = cache._cache_dir / f"{cache_key}.jpg"
    assert disk_path.exists(), "Cache file was not written to disk"
    print("PASS (d): Cover request writes .jpg, deduplicates inflight requests.")
    
    # Test (e): make_reflection
    src_pm = QPixmap.fromImage(emitted_img)
    refl_pm = make_reflection(src_pm)
    assert not refl_pm.isNull(), "Reflection pixmap is null"
    
    refl_img = refl_pm.toImage()
    top_color = refl_img.pixelColor(refl_img.width() // 2, 0)
    bottom_color = refl_img.pixelColor(refl_img.width() // 2, refl_img.height() - 1)
    
    assert top_color.alpha() > bottom_color.alpha(), f"Expected top alpha ({top_color.alpha()}) > bottom alpha ({bottom_color.alpha()})"
    print("PASS (e): make_reflection returns image with gradient alpha (top more opaque).")

    # Test (g): after a worker completes, the next request() for that key returns a pixmap WITHOUT the .jpg being read again
    # delete or rename the cache file after the worker finishes and assert request() still returns a valid pixmap from memory
    disk_path.unlink()
    pm3 = cache.request(node, 200)
    assert pm3 is not None, "Expected pixmap directly from memory cache"
    print("PASS (g): request() hits memory cache without reading .jpg.")
    
    # Test (i): an unrenderable file resolves without stranding its key.
    # mtime is unique per run so the cache_key is fresh: an unrenderable file
    # now yields a fallback card which IS cached, so a stale entry from an
    # earlier run would turn this into a cache hit and prove nothing.
    import time as _time
    bad_pdf_path = cache._cache_dir.parent / "scratch_bad.pdf"
    bad_pdf_path.write_text("not a pdf")
    bad_node = LibraryNode(path=bad_pdf_path, name="Bad PDF", is_dir=False,
                           size=0, mtime=_time.time())
    bad_key = f"{bad_node.cache_key}_200"

    loop2 = QEventLoop()
    def on_ready_bad(k, i):
        if k == bad_key:
            loop2.quit()

    cache.ready.connect(on_ready_bad)
    pm_bad = cache.request(bad_node, 200)
    assert pm_bad is None, f"expected an async miss for a fresh key, got {pm_bad}"
    loop2.exec()

    assert bad_key not in cache._inflight, "key left in _inflight after failure"
    # And the retry now resolves to something drawable rather than nothing.
    assert cache.request(bad_node, 200) is not None, (
        "an unrenderable file should still end up with a fallback preview")
    print("PASS (i): an unrenderable file clears _inflight and resolves to a "
          "fallback card.")
    
    # Test (h): a folder where one of several PDFs is unrenderable still produces art for the others
    # assert the fade target reaches 1.0 and that the failed one yields a placeholder
    from app.navigation import ScreenStack
    from app.application import Stage
    from app.screens.menu_screen import MenuScreen, MenuRow
    
    # Wide enough to be past theme.ART_MIN_W: below the breakpoint the preview
    # panel is dropped and no covers are fetched at all, which is the point of
    # the narrow layout but would make this test vacuous.
    stage = Stage()
    stage.resize(1100, 720)
    stack = ScreenStack(stage)
    stage.set_stack(stack)
    
    folder_node = LibraryNode(path=Path("dummy"), name="Folder", is_dir=True)
    folder_node.docs = [node, bad_node] # one good (already in cache), one bad (will be requested and fail)
    
    row = MenuRow(label="Folder", kind="folder", node=folder_node)
    screen = MenuScreen(stack, "Test", [row])
    
    screen.on_enter()
    screen._fetch_art()

    # art_anim should target 1.0 immediately because `docs` isn't empty
    assert screen.art_anim._target == 1.0, "Fade target did not reach 1.0"

    # Wait for both slots. The art panel requests at theme.COVER_REQ_W, so this
    # must not hardcode a width — that is what silently broke when covers were
    # enlarged from 360 to 480.
    import time
    from app import theme as theme_mod
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and not all(screen.art_pmaps):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.02)

    assert screen.art_pmaps[0] is not None, (
        f"good node art missing at width {theme_mod.COVER_REQ_W}")
    assert screen.art_pmaps[1] is not None, (
        "bad node art missing — a card should stand in for an unrenderable file")
    print(f"PASS (h): a folder with one unrenderable file still shows art for "
          f"the rest (requested at {theme_mod.COVER_REQ_W}px).")

if __name__ == "__main__":
    test_covers()
