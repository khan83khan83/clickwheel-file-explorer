"""Design tokens.

Two palettes, dark and light, chosen from the OS colour scheme at runtime and
re-resolved when Windows is flipped between light and dark.

Everything here is in REAL pixels. There is no logical canvas and no global
scale transform: screens paint at the window's own resolution, so text and page
bitmaps are natively crisp and the layout reflows when the window is resized.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication

# ---------------------------------------------------------------- metrics (px)

TITLEBAR_H = 44

ROW_H = 40
ROW_RADIUS = 8
ROW_PAD_L = 14
ROW_PAD_R = 34
CHEVRON_INSET = 18

LIST_FRAC = 0.36            # of window width
LIST_MIN = 250
LIST_MAX = 440

# Below this window width the preview panel is dropped and the list takes the
# whole width. A cramped preview is worse than none: it squeezes the labels you
# actually navigate by in order to show a thumbnail too small to read.
ART_MIN_W = 720

# Wrap-around feedback. Snapping straight to the far end is invisible — the
# selection simply appears elsewhere with no hint that it looped. Instead the
# view starts a short distance back along the direction of travel and slides
# in quickly, so the motion itself says "continued past the end".
# Only the list wraps. Cover Flow shows its neighbours on screen, so looping
# there would contradict what the user is looking at; it stops at both ends.
MENU_SCROLL_TAU = 0.055     # normal row-to-row scrolling
CF_POS_TAU = 0.075          # normal cover-to-cover movement
WRAP_TAU = 0.040            # snappier, so the loop reads as deliberate
WRAP_SLIDE_ROWS = 1.5       # how far the list slides in on a wrap

ART_PAD = 18
ART_LABEL_H = 52            # space reserved under the art for title + subtitle
CARD_RADIUS = 6

SCROLLBAR_W = 4
SCROLLBAR_INSET = 4

RESIZE_MARGIN = 6           # frameless window edge grab zone

# One request width shared by the art panel and Cover Flow, so a cover fetched
# for one is reused by the other. Fixed rather than window-derived: a dynamic
# width would give every resize its own cache key and re-render everything.
# 480 rather than 360 because a maximised art panel draws a single cover well
# past 400px wide, and upscaling past the source is what makes it look soft.
COVER_REQ_W = 480

# Reader. Currently shelved — PDFs open in Edge — but kept working so it can be
# switched back on without a rewrite.
PAGE_GAP = 14
PAGE_MARGIN_X = 24
HUD_H = 52
HUD_MARGIN = 14
HUD_RADIUS = 10

# Cover Flow geometry that is genuinely constant; sizes derive from the window.
CF_ANGLE = 62.0
CF_PERSP_D = 380.0          # default for perspective_y; screens pass their own
CF_PERSP_RATIO = 3.2        # perspective distance as a multiple of cover width
CF_SIDE_SCALE = 0.86
CF_RANGE = 5
CF_GAP_FRAC = 0.47          # x offset of the +/-1 cover, as a fraction of cover width
CF_STEP_FRAC = 0.22         # extra x per further index
REFLECT_FRAC = 0.5
REFLECT_ALPHA = 0.28

# Cover Flow sizing, as fractions of the content area.
CF_HEIGHT_FRAC = 0.66       # of content height
CF_HEIGHT_RESERVE = 92      # px of headroom before a cover stops growing
CF_WIDTH_CAP = 0.44         # a cover never exceeds this share of the width
CF_CENTRE_Y_FRAC = 0.40     # vertical centre of the fan
# Covers and their reflections are clipped above this bottom band so the title
# always sits on clean background. Without it a tall cover's reflection reaches
# the floor and the label disappears into it.
CF_LABEL_BAND = 70

# ------------------------------------------------------------------- palettes

_DARK = {
    "WINDOW_BG":     "#191919",
    "SURFACE":       "#202020",
    "SURFACE_ALT":   "#262626",
    "BORDER":        "#2E2E2E",
    "TITLEBAR_BG":   "#191919",
    "TEXT":          "#EDEDED",
    "TEXT_DIM":      "#8C8C8C",
    "TEXT_FAINT":    "#5F5F5F",
    "ACCENT":        "#4C8DFF",
    "SEL_BG":        "#4C8DFF",
    "SEL_TEXT":      "#FFFFFF",
    "HOVER_BG":      "#242424",
    "CHEVRON":       "#7A7A7A",
    "CHEVRON_SEL":   "#FFFFFF",
    "SCROLL_THUMB":  "#4A4A4A",
    "CF_BG":         "#141414",
    "CF_BG_EDGE":    "#0B0B0B",
    "CARD_BG":       "#2A2A2A",
    "CARD_EDGE":     "rgba(255,255,255,26)",
    "SHADOW":        "rgba(0,0,0,150)",
    "PAGE_BG":       "#FFFFFF",
    "PAGE_BORDER":   "#000000",
    "READER_GUTTER": "#101010",
    "HUD_BG":        "rgba(24,24,24,225)",
    "HUD_BAR_BG":    "#3A3A3A",
    "HUD_BAR_FILL":  "#4C8DFF",
    # Windows 11 flyout / navigation-pane surface, so the docked panel reads as
    # part of the shell rather than as a floating app window.
    "PANEL_BASE":    "#1F262D",
    "PANEL_BORDER":  "#333333",
}

_LIGHT = {
    "WINDOW_BG":     "#FAFAFA",
    "SURFACE":       "#FFFFFF",
    "SURFACE_ALT":   "#F1F1F1",
    "BORDER":        "#E4E4E4",
    "TITLEBAR_BG":   "#FAFAFA",
    "TEXT":          "#1B1B1B",
    "TEXT_DIM":      "#6B6B6B",
    "TEXT_FAINT":    "#9A9A9A",
    "ACCENT":        "#0A66E0",
    "SEL_BG":        "#0A66E0",
    "SEL_TEXT":      "#FFFFFF",
    "HOVER_BG":      "#EDEDED",
    "CHEVRON":       "#9A9A9A",
    "CHEVRON_SEL":   "#FFFFFF",
    "SCROLL_THUMB":  "#C6C6C6",
    "CF_BG":         "#EFEFEF",
    "CF_BG_EDGE":    "#D9D9D9",
    "CARD_BG":       "#FFFFFF",
    "CARD_EDGE":     "rgba(0,0,0,28)",
    "SHADOW":        "rgba(0,0,0,45)",
    "PAGE_BG":       "#FFFFFF",
    "PAGE_BORDER":   "#C8C8C8",
    "READER_GUTTER": "#E8E8E8",
    "HUD_BG":        "rgba(250,250,250,235)",
    "HUD_BAR_BG":    "#D4D4D4",
    "HUD_BAR_FILL":  "#0A66E0",
    "PANEL_BASE":    "#E2EDF7",
    "PANEL_BORDER":  "#E0E0E0",
}

_mode = "dark"              # "dark" | "light"
_override = None            # None = follow the OS
_listeners = []


def _detect_system() -> str:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return "light"
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
    except (AttributeError, RuntimeError):
        pass                                    # Qt < 6.5, or no QGuiApplication yet
    try:                                        # Windows fallback
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return "light" if val else "dark"
    except Exception:
        return "dark"


def init_theme(on_change=None) -> None:
    """Resolve the palette now, and follow the OS if it changes later."""
    global _mode
    _mode = _override or _detect_system()
    if on_change and on_change not in _listeners:
        _listeners.append(on_change)
    try:
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _s: _refresh())
    except (AttributeError, RuntimeError):
        pass


def _refresh() -> None:
    global _mode
    new = _override or _detect_system()
    if new != _mode:
        _mode = new
        for fn in list(_listeners):
            fn()


def mode() -> str:
    return _mode


def set_mode(m) -> None:
    """'dark', 'light', or None to follow the system."""
    global _override, _mode
    _override = m if m in ("dark", "light") else None
    _mode = _override or _detect_system()
    for fn in list(_listeners):
        fn()


def is_dark() -> bool:
    return _mode == "dark"


# --------------------------------------------------------------------- lookup

_RGBA = re.compile(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)")


def color(token: str) -> QColor:
    table = _DARK if _mode == "dark" else _LIGHT
    c = table.get(token) or _DARK.get(token)
    if c is None:
        raise KeyError(f"theme.color: unknown token {token!r}")
    m = _RGBA.match(c)
    if m:
        return QColor(*(int(m.group(i)) for i in (1, 2, 3, 4)))
    return QColor(c)


def mix(a: str, b: str, t: float) -> QColor:
    ca, cb = color(a), color(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t))


# ---------------------------------------------------------------------- fonts

_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Liberation Sans", "Arial"]

_SPEC = {
    "F_TITLE":       (13, QFont.Weight.DemiBold),
    "F_ROW":         (14, QFont.Weight.Normal),
    "F_ROW_SEL":     (14, QFont.Weight.DemiBold),
    "F_ROW_VALUE":   (13, QFont.Weight.Normal),
    "F_ART_TITLE":   (15, QFont.Weight.DemiBold),
    "F_ART_SUB":     (12, QFont.Weight.Normal),
    "F_COVER_TITLE": (17, QFont.Weight.DemiBold),
    "F_COVER_SUB":   (13, QFont.Weight.Normal),
    "F_EMPTY":       (14, QFont.Weight.Normal),
    "F_PLACEHOLDER": (11, QFont.Weight.Normal),
}

_warned = False


def font(token: str) -> QFont:
    global _warned
    if not _warned:
        _warned = True
        fams = set(QFontDatabase.families())
        if not any(f in fams for f in _FAMILIES[:2]):
            print("NOTE: Segoe UI not found; using a generic sans fallback.")
    size, weight = _SPEC.get(token, (14, QFont.Weight.Normal))
    f = QFont()
    f.setFamilies(_FAMILIES)
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def list_width(win_w: int) -> int:
    return int(max(LIST_MIN, min(LIST_MAX, win_w * LIST_FRAC)))


# ------------------------------------------------------------ system accent

_ACCENT_CACHE = None

# How far the docked panel is tinted from its neutral base toward the system
# accent. Windows tints its taskbar and flyout acrylic the same way, which is
# why a purely neutral grey reads as flat white beside them.
PANEL_TINT = {"light": 0.0, "dark": 0.0}


def system_accent() -> QColor:
    """The Windows accent colour, or the app's own if it cannot be read."""
    global _ACCENT_CACHE
    if _ACCENT_CACHE is not None:
        return _ACCENT_CACHE
    c = None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\DWM") as k:
            raw, _ = winreg.QueryValueEx(k, "AccentColor")
        # Stored as ABGR, not ARGB.
        c = QColor(raw & 0xFF, (raw >> 8) & 0xFF, (raw >> 16) & 0xFF)
    except Exception:
        c = None
    _ACCENT_CACHE = c or QColor(color("ACCENT"))
    return _ACCENT_CACHE


def panel_bg() -> QColor:
    """The docked panel's surface.

    Prefers an explicit "panel_color" measured from the taskbar
    (tools/sample_taskbar.py --apply). The taskbar is acrylic over the
    wallpaper, so no registry value predicts it and deriving from the accent
    alone lands far too saturated. Falls back to the base, optionally blended
    toward the accent by "panel_tint".
    """
    try:
        from app import config
        explicit = config.get("panel_color")
        # Keyed by theme: a colour measured off the light taskbar says nothing
        # about the dark one, and using it in dark mode would be glaringly wrong.
        if isinstance(explicit, dict):
            explicit = explicit.get(_mode)
        elif explicit:
            explicit = None         # legacy single value: ignore rather than misapply
        if explicit:
            c = QColor(explicit)
            if c.isValid():
                return c
    except Exception:
        pass
    base = color("PANEL_BASE")
    acc = system_accent()
    t = PANEL_TINT.get(_mode, 0.16)
    try:                                # "panel_tint" in config.json overrides
        from app import config
        override = config.get("panel_tint")
        if override is not None:
            t = max(0.0, min(1.0, float(override)))
    except Exception:
        pass
    return QColor(round(base.red() + (acc.red() - base.red()) * t),
                  round(base.green() + (acc.green() - base.green()) * t),
                  round(base.blue() + (acc.blue() - base.blue()) * t))
