from PySide6.QtGui import QPixmap, QImage, QPainter, QLinearGradient, QColor
from PySide6.QtCore import QRect, Qt
from app import theme

def make_reflection(src: QPixmap, frac: float = theme.REFLECT_FRAC, top_alpha: float = theme.REFLECT_ALPHA) -> QPixmap:
    img = src.toImage().mirrored(False, True)
    
    h = int(img.height() * frac)
    w = img.width()
    if h == 0:
        return QPixmap()
        
    crop = img.copy(0, 0, w, h)
    
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    
    p = QPainter(out)
    p.drawImage(0, 0, crop)
    
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0.0, QColor(0, 0, 0, int(255 * top_alpha)))
    grad.setColorAt(1.0, QColor(0, 0, 0, 0))
    
    p.fillRect(0, 0, w, h, grad)
    p.end()
    
    return QPixmap.fromImage(out)
