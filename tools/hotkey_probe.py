"""Is Win+W claimable by an application yet?

While the shell owns a Win+<key> combination, RegisterHotKey fails with
ERROR_HOTKEY_ALREADY_REGISTERED (1409). Run this after each attempt at freeing
the key to see whether it actually worked, instead of guessing from whether the
Widgets board still appears.

    python tools/hotkey_probe.py

Prints a verdict per combination, then listens for 30 seconds so you can press
the ones that registered and confirm they reach this process.
"""
import ctypes
import sys
import time
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows only.")

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001

ERRORS = {
    0: "no error reported",
    1409: "ERROR_HOTKEY_ALREADY_REGISTERED — something else owns it "
          "(the shell, or another app)",
    1419: "ERROR_HOTKEY_NOT_REGISTERED",
    87: "ERROR_INVALID_PARAMETER",
}

CANDIDATES = [
    (1, MOD_WIN, ord("W"), "Win+W            <- the one you want"),
    (2, MOD_WIN | MOD_SHIFT, ord("W"), "Win+Shift+W"),
    (3, MOD_WIN | MOD_SHIFT, ord("P"), "Win+Shift+P"),
    (4, MOD_CONTROL | MOD_ALT, ord("P"), "Ctrl+Alt+P"),
]


def main():
    registered = {}
    width = max(len(label) for _, _, _, label in CANDIDATES)

    print("Attempting to register global hotkeys...\n")
    for hk_id, mods, vk, label in CANDIDATES:
        ok = user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk)
        if ok:
            registered[hk_id] = label
            print(f"  {label:<{width}}  AVAILABLE")
        else:
            err = ctypes.get_last_error()
            why = ERRORS.get(err, f"error {err}")
            print(f"  {label:<{width}}  BLOCKED    ({why})")

    print()
    if 1 in registered:
        print("Win+W is FREE — the app can own it. Press it now to confirm.")
    else:
        print("Win+W is still held by Windows. Try the next technique, then "
              "re-run this.")

    if not registered:
        print("Nothing registered; exiting.")
        return

    print("Listening for 30 seconds — press any hotkey listed as AVAILABLE.\n")
    msg = wintypes.MSG()
    end = time.monotonic() + 30
    seen = set()
    while time.monotonic() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_HOTKEY:
                label = registered.get(msg.wParam, f"id {msg.wParam}")
                if msg.wParam not in seen:
                    seen.add(msg.wParam)
                print(f"  received: {label.strip()}")
        time.sleep(0.02)

    for hk_id in registered:
        user32.UnregisterHotKey(None, hk_id)

    print()
    if 1 in seen:
        print("CONFIRMED: Win+W reached this process. It is yours to use.")
    elif 1 in registered:
        print("Win+W registered but no press was received — either you did not "
              "press it, or something upstream is still swallowing it.")
    print("Done; hotkeys released.")


if __name__ == "__main__":
    main()
