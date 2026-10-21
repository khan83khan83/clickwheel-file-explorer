"""System-wide hotkey registration (Windows).

RegisterHotKey is bound to the app's own window handle, so WM_HOTKEY arrives at
that window and Stage.nativeEvent can pick it up — no application-wide event
filter needed. A hidden window still receives it, which is what makes summoning
from nowhere work.
"""
import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

_MODS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN,
}

_NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}

_ERRORS = {
    1409: "already registered — another application or the Windows shell owns it",
    87: "invalid parameter — check the key name",
}

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:                                           # tests import this off-Windows
    _user32 = None


class HotkeyError(Exception):
    pass


def parse_spec(spec: str):
    """'ctrl+e' -> (MOD_CONTROL, 0x45). Raises HotkeyError on nonsense."""
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts:
        raise HotkeyError("empty hotkey specification")

    mods = 0
    key = None
    for part in parts:
        if part in _MODS:
            mods |= _MODS[part]
        elif key is None:
            key = part
        else:
            raise HotkeyError(f"more than one non-modifier key in {spec!r}")

    if key is None:
        raise HotkeyError(f"{spec!r} has modifiers but no key")

    if key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise HotkeyError(f"unrecognised key {key!r} in {spec!r}")

    if mods == 0:
        raise HotkeyError(f"{spec!r} needs at least one modifier; a bare key "
                          f"cannot be a global hotkey")
    return mods, vk


def describe(spec: str) -> str:
    """Tidy a spec for display: 'ctrl+e' -> 'Ctrl+E'."""
    try:
        parts = [p.strip() for p in str(spec).split("+") if p.strip()]
    except Exception:
        return str(spec)
    pretty = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
              "win": "Win", "meta": "Win", "super": "Win"}
    return "+".join(pretty.get(p.lower(), p.upper() if len(p) == 1 else p.title())
                    for p in parts)


def register(hwnd, hotkey_id: int, spec: str) -> None:
    """Claim `spec` system-wide. Raises HotkeyError if Windows refuses.

    Pass hwnd=None to bind the hotkey to the THREAD rather than a window.
    That matters here: toggling the taskbar flag destroys and recreates the
    native window handle, which would silently orphan a window-bound hotkey.
    Thread-bound registration survives it.
    """
    if _user32 is None:
        raise HotkeyError("global hotkeys are Windows-only")
    mods, vk = parse_spec(spec)
    if not _user32.RegisterHotKey(hwnd, hotkey_id, mods | MOD_NOREPEAT, vk):
        err = ctypes.get_last_error()
        raise HotkeyError(f"could not register {describe(spec)}: "
                          f"{_ERRORS.get(err, f'error {err}')}")


def unregister(hwnd, hotkey_id: int) -> None:
    if _user32 is not None:
        _user32.UnregisterHotKey(hwnd, hotkey_id)


class HotkeyFilter(QAbstractNativeEventFilter):
    """Routes thread-bound WM_HOTKEY messages to a callback.

    A thread-bound hotkey has no window to deliver to, so it lands in the
    thread's message queue; Qt hands those to application-level native event
    filters. Keep a reference to this object alive or Qt drops the filter.
    """

    def __init__(self, hotkey_id: int, callback):
        super().__init__()
        self._id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG" and is_hotkey_message(message, self._id):
            self._callback()
            return True, 0
        return False, 0


def is_hotkey_message(message, hotkey_id: int) -> bool:
    """True when a native MSG is our WM_HOTKEY.

    PySide6 hands `message` over in a few different shapes depending on build,
    so try each rather than assuming one.
    """
    if _user32 is None:
        return False
    from ctypes import wintypes
    addr = None
    for get in (lambda: message.__int__(), lambda: int(message)):
        try:
            addr = get()
            break
        except (AttributeError, TypeError, ValueError):
            continue
    if not addr:
        return False
    try:
        msg = wintypes.MSG.from_address(addr)
    except (ValueError, TypeError):
        return False
    return msg.message == WM_HOTKEY and msg.wParam == hotkey_id
