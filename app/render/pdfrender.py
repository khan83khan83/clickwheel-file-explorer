"""Asynchronous PDF page rendering with a byte-capped LRU cache (§6.5).

One dedicated worker thread, not a pool: page bitmaps are large and rendering
them sequentially avoids the memory spikes a pool would cause. Requests are
pushed to the FRONT of the queue so the page nearest the viewport wins.

Threading contract (§13.1-3):
  - the worker only ever produces QImage; QPixmap is built on the GUI thread
  - the worker owns its own fitz.Document and never shares it
  - QImages are copied off the fitz buffer before they leave the worker
"""
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

from app.library.document import Doc

CACHE_BYTES_MAX = 60 * 1024 * 1024      # §6.5

# Queue sentinel: tells the worker to close its open document and keep waiting.
_RELEASE = ("__release__", -1, 0.0)


@dataclass
class DocMeta:
    page_count: int
    sizes: list = field(default_factory=list)   # [(w_pt, h_pt), ...]


def zoom_bucket(zoom: float) -> float:
    """Requests are keyed by a rounded zoom so tiny scroll-induced drifts reuse
    the same bitmap instead of thrashing the cache."""
    return round(zoom, 2)


class _RenderSignals(QObject):
    ready = Signal(str, int, float, QImage)


class PdfRenderer(QObject):
    ready = Signal(str, int, float, QImage)     # path, page, zoom_bucket, image

    def __init__(self):
        super().__init__()
        self._signals = _RenderSignals()
        self._signals.ready.connect(self._on_ready)

        self._cache: OrderedDict = OrderedDict()    # (path, page, zb) -> QPixmap
        self._bytes = 0
        self._inflight = set()

        self._queue: deque = deque()
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="pdf-render")
        self._thread.start()

    # ---------------------------------------------------------------- public

    def open(self, path: Path) -> DocMeta:
        """Read page count and every page's size. GUI thread; a few ms even for
        several hundred pages, and the reader cannot lay out without it."""
        doc = Doc(path)
        try:
            n = doc.page_count()
            sizes = [doc.page_size(i) for i in range(n)]
            return DocMeta(page_count=n, sizes=sizes)
        finally:
            doc.close()

    def request(self, path: Path, page: int, zoom: float) -> QPixmap | None:
        zb = zoom_bucket(zoom)
        key = (str(path), page, zb)

        pm = self._cache.get(key)
        if pm is not None:
            self._cache.move_to_end(key)
            return pm

        if key not in self._inflight:
            self._inflight.add(key)
            with self._cv:
                self._queue.appendleft((str(path), page, zb))
                self._cv.notify()
        return None

    def peek(self, path: Path, page: int, zoom: float) -> QPixmap | None:
        """Cache lookup with no side effects. paint() uses this; everything else
        uses request()."""
        pm = self._cache.get((str(path), page, zoom_bucket(zoom)))
        return pm

    def cancel_all(self) -> None:
        """Drop everything queued. In-flight work finishes but its result is
        simply cached; nothing is waiting on it."""
        with self._cv:
            for item in self._queue:
                self._inflight.discard(item)
            self._queue.clear()

    def release(self) -> None:
        """Make the worker close whatever document it is holding.

        The worker keeps a document open between requests so consecutive pages
        are cheap, which also means it keeps a file handle on the PDF. Without
        this, the last document read stays locked for the life of the process
        and Windows refuses to let the user delete or move it."""
        with self._cv:
            self._queue.appendleft(_RELEASE)
            self._cv.notify()

    def shutdown(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()

    # ---------------------------------------------------------------- worker

    def _run(self) -> None:
        doc = None
        doc_path = None
        try:
            while True:
                with self._cv:
                    while not self._queue and not self._stop:
                        self._cv.wait()
                    if self._stop:
                        return
                    task = self._queue.popleft()

                if task is _RELEASE:
                    if doc is not None:
                        doc.close()
                    doc, doc_path = None, None
                    continue

                path, page, zb = task
                try:
                    if doc_path != path:
                        if doc is not None:
                            doc.close()
                        doc = Doc(Path(path))
                        doc_path = path
                    img = doc.render(page, zb)
                except Exception as e:          # corrupt page, bad zoom, etc.
                    print(f"PdfRenderer error on {path} p{page}: {e}")
                    img = QImage()
                    if doc is not None:
                        doc.close()
                    doc, doc_path = None, None

                self._signals.ready.emit(path, page, zb, img)
        finally:
            if doc is not None:
                doc.close()

    # ------------------------------------------------------------- GUI thread

    def _on_ready(self, path: str, page: int, zb: float, img: QImage) -> None:
        key = (path, page, zb)
        self._inflight.discard(key)
        if not img.isNull():
            self._put(key, QPixmap.fromImage(img))
        self.ready.emit(path, page, zb, img)

    def _put(self, key, pm: QPixmap) -> None:
        cost = pm.width() * pm.height() * 4
        self._cache[key] = pm
        self._bytes += cost
        while self._bytes > CACHE_BYTES_MAX and len(self._cache) > 1:
            _, old = self._cache.popitem(last=False)
            self._bytes -= old.width() * old.height() * 4

    def drop_document(self, path: Path) -> None:
        """Forget every cached page of one document."""
        s = str(path)
        for key in [k for k in self._cache if k[0] == s]:
            pm = self._cache.pop(key)
            self._bytes -= pm.width() * pm.height() * 4


renderer = PdfRenderer()
