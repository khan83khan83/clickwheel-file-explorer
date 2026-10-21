from pathlib import Path
from collections import OrderedDict
from multiprocessing import cpu_count
from PySide6.QtCore import QObject, Signal, QThreadPool, QRunnable
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFontMetrics, QPen
from PySide6.QtCore import Qt, QRect

from app.library.model import LibraryNode
from app.library.document import Doc
from app.library import preview
from app import theme

class CoverWorker(QRunnable):
    def __init__(self, node: LibraryNode, target_w: int, cache_path: Path, signals: 'CoverSignals'):
        super().__init__()
        self.node = node
        self.target_w = target_w
        self.cache_path = cache_path
        self.signals = signals

    def run(self):
        doc = None
        img = QImage()
        try:
            if preview.kind(self.node.path) == "pdf":
                try:
                    doc = Doc(self.node.path)
                    w, _ = doc.page_size(0)
                    img = doc.render(0, self.target_w / w)
                except Exception:
                    img = QImage()      # broken PDF: fall through to a preview
            if img.isNull():
                img = preview.render_preview(self.node.path, self.node.name,
                                             self.target_w)

            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(self.cache_path), "JPG", 88)
        except Exception as e:
            print(f"CoverWorker error: {e}")
        finally:
            if doc:
                doc.close()
            key = f"{self.node.cache_key}_{self.target_w}"
            self.signals.ready.emit(key, img)

class CoverSignals(QObject):
    ready = Signal(str, QImage)

class CoverCache(QObject):
    ready = Signal(str, QImage)

    def __init__(self):
        super().__init__()
        self._mem = OrderedDict()
        self._inflight = set()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(min(4, cpu_count()))
        self._signals = CoverSignals()
        self._signals.ready.connect(self._on_worker_ready)
        self._placeholder_cache = {}
        
        from app import config
        self._cache_dir = config.COVERS_DIR

    def _on_worker_ready(self, key: str, img: QImage):
        self._inflight.discard(key)
        if not img.isNull():
            self._put(key, QPixmap.fromImage(img))
        self.ready.emit(key, img)

    def request(self, node: LibraryNode, target_w: int) -> QPixmap | None:
        key = f"{node.cache_key}_{target_w}"
        
        if key in self._mem:
            val = self._mem.pop(key)
            self._mem[key] = val
            return val
            
        disk_path = self._cache_dir / f"{key}.jpg"
        if disk_path.exists():
            pm = QPixmap(str(disk_path))
            if not pm.isNull():
                self._put(key, pm)
                return pm
                
        if key not in self._inflight:
            self._inflight.add(key)
            worker = CoverWorker(node, target_w, disk_path, self._signals)
            self._pool.start(worker)
            
        return None

    def _put(self, key: str, pm: QPixmap):
        # Covers are 480px wide, roughly 1.2 MB each as a QPixmap, so the entry
        # cap is set to keep this cache near 55 MB rather than by entry count.
        self._mem[key] = pm
        if len(self._mem) > 48:
            self._mem.popitem(last=False)

    def placeholder(self, node: LibraryNode) -> QPixmap:
        if node.cache_key in self._placeholder_cache:
            return self._placeholder_cache[node.cache_key]
            
        w = theme.COVER_REQ_W
        h = int(w * 1.3)
        pm = QPixmap(w, h)
        pm.fill(theme.color("CARD_BG"))

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(theme.color("BORDER"), 2))
        p.drawRect(1, 1, w - 2, h - 2)

        f = theme.font("F_ART_SUB")
        f.setPixelSize(max(14, w // 18))
        p.setFont(f)
        p.setPen(theme.color("TEXT_DIM"))
        pad = w // 12
        rect = QRect(pad, pad, w - 2 * pad, h - 2 * pad)
        p.drawText(rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop
                   | Qt.AlignmentFlag.AlignHCenter, node.name)
        p.end()
        
        self._placeholder_cache[node.cache_key] = pm
        return pm

cache = CoverCache()
