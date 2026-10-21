"""Windows shell thumbnails.

Explorer shows a real frame for a video, a first page for a Word document and a
preview for a PSD because each file type ships a thumbnail provider. The shell
exposes that through IShellItemImageFactory, so rather than shipping a video
decoder we ask Windows for the same bitmap it would draw itself.

`thumbnail()` returns a null QImage when a file has no provider — plain text,
source code, archives — and the caller falls back to a drawn card.
"""
import ctypes
import sys
import threading
from ctypes import POINTER, Structure, byref, c_void_p, wintypes
from pathlib import Path

from PySide6.QtGui import QImage

_IS_WIN = sys.platform == "win32"

# IShellItemImageFactory::GetImage flags
SIIGBF_RESIZETOFIT = 0x00
SIIGBF_BIGGERSIZEOK = 0x01
SIIGBF_THUMBNAILONLY = 0x08     # never fall back to the file-type icon

S_OK = 0
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850
DIB_RGB_COLORS = 0


class GUID(Structure):
    _fields_ = [("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SIZE(Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BITMAP(Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", c_void_p)]


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _guid(s: str) -> GUID:
    g = GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), byref(g)) != S_OK:
        raise OSError(f"bad GUID {s}")
    return g


if _IS_WIN:
    _shell32 = ctypes.windll.shell32
    _ole32 = ctypes.windll.ole32
    _gdi32 = ctypes.windll.gdi32
    _user32 = ctypes.windll.user32
    IID_IShellItemImageFactory = _guid("{BCC18B79-BA16-442F-80C4-8A59C30C463B}")

_tls = threading.local()


def _ensure_com() -> None:
    """COM is per-thread, and cover rendering happens on pool threads."""
    if getattr(_tls, "ready", False):
        return
    hr = _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    # RPC_E_CHANGED_MODE means the thread is already initialised differently,
    # which is fine — we just must not uninitialise it.
    if hr == S_OK or hr == 1 or hr == RPC_E_CHANGED_MODE:
        _tls.ready = True


def _hbitmap_to_qimage(hbm) -> QImage:
    bm = BITMAP()
    if not _gdi32.GetObjectW(hbm, ctypes.sizeof(BITMAP), byref(bm)):
        return QImage()
    w, h = int(bm.bmWidth), int(bm.bmHeight)
    if w <= 0 or h <= 0:
        return QImage()

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h          # negative: top-down rows
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0      # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = _user32.GetDC(None)
    try:
        got = _gdi32.GetDIBits(hdc, hbm, 0, h, buf, byref(bmi), DIB_RGB_COLORS)
    finally:
        _user32.ReleaseDC(None, hdc)
    if not got:
        return QImage()

    # Shell thumbnails come back BGRA premultiplied, which is exactly what
    # Format_ARGB32_Premultiplied expects on little-endian.
    img = QImage(buf, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied)
    return img.copy()                    # detach from the temporary buffer


def thumbnail(path: Path, size: int) -> QImage:
    """The bitmap Explorer would show, or a null QImage if there is none."""
    if not _IS_WIN:
        return QImage()
    try:
        _ensure_com()
        factory = c_void_p()
        hr = _shell32.SHCreateItemFromParsingName(
            ctypes.c_wchar_p(str(Path(path).resolve())), None,
            byref(IID_IShellItemImageFactory), byref(factory))
        if hr != S_OK or not factory:
            return QImage()

        try:
            vtbl = ctypes.cast(factory,
                               POINTER(POINTER(c_void_p))).contents
            # vtable slot 3: GetImage(SIZE, int, HBITMAP*)
            GetImage = ctypes.WINFUNCTYPE(
                ctypes.c_long, c_void_p, SIZE, ctypes.c_int,
                POINTER(wintypes.HBITMAP))(vtbl[3])
            Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl[2])

            hbm = wintypes.HBITMAP()
            hr = GetImage(factory, SIZE(size, size),
                          SIIGBF_BIGGERSIZEOK | SIIGBF_THUMBNAILONLY, byref(hbm))
            if hr != S_OK or not hbm:
                return QImage()
            try:
                return _hbitmap_to_qimage(hbm)
            finally:
                _gdi32.DeleteObject(hbm)
        finally:
            Release(factory)
    except Exception as e:
        print(f"winthumb: {Path(path).name}: {e}")
        return QImage()
