"""What a file looks like in the browser.

Three kinds of preview:
  PDF     -> first page, rendered
  image   -> the image itself
  other   -> a generated card showing the extension, tinted by category

The generated card is deliberate rather than a Windows shell icon: shell icons
come in fixed small sizes and look mushy blown up to a 480px cover, whereas a
drawn card stays crisp and sits consistently beside the real page renders.
"""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QLinearGradient,
                           QPainter, QPainterPath)

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# Extension -> (category label, accent colour). Anything unlisted gets the
# neutral default, so the browser never shows a blank card.
_CATEGORY = {
    "video": (["mp4", "mkv", "avi", "mov", "wmv", "webm", "m4v", "flv"], "#C2410C"),
    "audio": (["mp3", "wav", "flac", "m4a", "aac", "ogg", "wma", "mid", "midi"], "#7C3AED"),
    "doc":   (["doc", "docx", "rtf", "odt", "txt", "md", "tex"], "#1D4ED8"),
    "sheet": (["xls", "xlsx", "csv", "tsv", "ods"], "#15803D"),
    "slide": (["ppt", "pptx", "odp", "key"], "#B45309"),
    "code":  (["py", "js", "ts", "c", "cpp", "h", "java", "cs", "rs", "go",
               "html", "css", "json", "xml", "yml", "yaml", "sh", "ps1"], "#0F766E"),
    "archive": (["zip", "rar", "7z", "tar", "gz", "iso"], "#4B5563"),
    "exe":   (["exe", "msi", "bat", "cmd", "lnk", "dll"], "#9F1239"),
}

_COLOUR_BY_EXT = {}
for _cat, (_exts, _colour) in _CATEGORY.items():
    for _e in _exts:
        _COLOUR_BY_EXT[_e] = _colour

_DEFAULT_COLOUR = "#475569"


def kind(path: Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"


def accent_for(path: Path) -> QColor:
    ext = Path(path).suffix.lower().lstrip(".")
    return QColor(_COLOUR_BY_EXT.get(ext, _DEFAULT_COLOUR))


def render_image(path: Path, target_w: int) -> QImage:
    """Load an image file scaled to the cover width. Null if unreadable."""
    img = QImage(str(path))
    if img.isNull():
        return QImage()
    if img.width() > target_w:
        img = img.scaledToWidth(target_w, Qt.TransformationMode.SmoothTransformation)
    return img.convertToFormat(QImage.Format.Format_RGB32)


def render_preview(path: Path, name: str, target_w: int) -> QImage:
    """Best available preview for a non-PDF file.

    Images load directly. Everything else asks Windows for the thumbnail it
    would show in Explorer — which covers video frames, Office first pages and
    anything else with a thumbnail provider. Only when there is no provider
    (plain text, source, archives) do we fall back to a drawn card.
    """
    k = kind(path)
    if k == "image":
        img = render_image(path, target_w)
        if not img.isNull():
            return img
    else:
        from app.library import winthumb
        img = winthumb.thumbnail(path, target_w)
        if not img.isNull():
            return img
    return render_card(path, name, target_w)


def render_card(path: Path, name: str, target_w: int) -> QImage:
    """A card showing the file's extension, tinted by category."""
    w = int(target_w)
    h = int(w * 1.3)
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    accent = accent_for(path)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    radius = w * 0.045
    body = QRectF(0, 0, w, h)
    path_shape = QPainterPath()
    path_shape.addRoundedRect(body, radius, radius)

    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0.0, accent.lighter(118))
    g.setColorAt(1.0, accent.darker(118))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(path_shape)

    ext = Path(path).suffix.lstrip(".").upper() or "FILE"
    if len(ext) > 5:
        ext = ext[:5]

    f = QFont()
    f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Arial"])
    f.setPixelSize(int(w * (0.30 if len(ext) <= 3 else 0.22)))
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    fm = QFontMetrics(f)
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(int(w / 2 - fm.horizontalAdvance(ext) / 2),
               int(h * 0.52 + fm.capHeight() / 2), ext)

    # Filename underneath, wrapped, so similar extensions stay distinguishable.
    f2 = QFont(f)
    f2.setPixelSize(int(w * 0.062))
    f2.setWeight(QFont.Weight.Normal)
    p.setFont(f2)
    p.setPen(QColor(255, 255, 255, 190))
    p.drawText(QRectF(w * 0.10, h * 0.60, w * 0.80, h * 0.30),
               int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter
                   | Qt.AlignmentFlag.AlignTop),
               name)
    p.end()
    return img
