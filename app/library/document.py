import fitz
from pathlib import Path
from PySide6.QtGui import QImage

class Doc:
    def __init__(self, path: Path):
        self._d = fitz.open(path)

    def page_count(self) -> int:
        return len(self._d)

    def page_size(self, i: int) -> tuple[float, float]:
        rect = self._d[i].rect
        return (rect.width, rect.height)

    def render(self, i: int, zoom: float) -> QImage:
        page = self._d.load_page(i)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888)
        return img.copy()

    def close(self) -> None:
        self._d.close()
