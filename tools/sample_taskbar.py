"""Sample the real colour of the Windows taskbar.

The taskbar is acrylic over the wallpaper, so its colour cannot be derived from
the accent or from any single registry value — it has to be measured off the
screen. Samples an empty strip and reports the median, which ignores icons and
highlights.
"""
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication          # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402


def sample():
    app = QApplication.instance() or QApplication(sys.argv)
    results = []
    for screen in QGuiApplication.screens():
        geo = screen.geometry()
        avail = screen.availableGeometry()
        # The taskbar is the strip the desktop excludes from the usable area.
        bar_h = geo.height() - avail.height()
        if bar_h <= 0:
            continue
        shot = screen.grabWindow(0).toImage()
        dpr = shot.width() / max(1, geo.width())

        y = int((avail.height() + bar_h / 2) * dpr)
        counts = Counter()
        # Skip the middle third, where the pinned icons live.
        for frac in [0.02, 0.05, 0.08, 0.11, 0.14, 0.17, 0.86, 0.89, 0.92]:
            x = int(geo.width() * frac * dpr)
            if 0 <= x < shot.width() and 0 <= y < shot.height():
                c = shot.pixelColor(x, y)
                counts[(c.red(), c.green(), c.blue())] += 1

        if not counts:
            continue
        # Median of each channel: robust against a stray icon pixel.
        reds = sorted(c[0] for c in counts.elements())
        greens = sorted(c[1] for c in counts.elements())
        blues = sorted(c[2] for c in counts.elements())
        mid = len(reds) // 2
        rgb = (reds[mid], greens[mid], blues[mid])
        results.append((screen.name(), bar_h, rgb, counts.most_common(4)))
    return results


if __name__ == "__main__":
    found = sample()
    for name, bar_h, rgb, common in found:
        hexv = "#%02x%02x%02x" % rgb
        print(f"{name}: taskbar {bar_h}px tall, median {hexv}  rgb={rgb}")
        for (r, g, b), n in common:
            print(f"    sampled #%02x%02x%02x x{n}" % (r, g, b))

    if "--apply" in sys.argv:
        if not found:
            print("no taskbar found to sample")
            sys.exit(1)
        # The screen the cursor is on is the one whose taskbar the user means.
        from PySide6.QtGui import QCursor
        target = QGuiApplication.screenAt(QCursor.pos())
        pick = next((f for f in found if target and f[0] == target.name()), found[0])
        hexv = "#%02x%02x%02x" % pick[2]
        from app import config, theme
        config.init()
        # Only ever writes the slot for the theme currently in use.
        mode = theme._detect_system()
        current = config.get("panel_color")
        if not isinstance(current, dict):
            current = {"light": None, "dark": None}
        current[mode] = hexv
        config.set_value("panel_color", current)
        print()
        print(f"applied panel_color[{mode}] = {hexv}  (from {pick[0]})")
        print("restart the app to see it")
