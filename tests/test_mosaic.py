"""The folder preview mosaic never distorts: every tile keeps its image's aspect
ratio, stays inside the box, and tiles never overlap."""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication                       # noqa: E402

from app.screens.menu_screen import mosaic_rects                 # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

VIDEO, PHOTO, COVER, SQUARE = 16 / 9, 3 / 2, 1 / 1.3, 1.0
CASES = [
    [VIDEO, SQUARE, VIDEO, VIDEO],          # the Vlog Material folder
    [COVER, COVER, COVER, COVER],
    [VIDEO, COVER],
    [VIDEO, VIDEO],
    [COVER, VIDEO, PHOTO],
    [9 / 16, VIDEO, 9 / 16, SQUARE],        # phone clips mixed in
]
BOXES = [(800, 760), (300, 820), (1200, 400), (180, 180)]


def test_undistorted_and_inside():
    for aspects in CASES:
        for bw, bh in BOXES:
            rects = mosaic_rects(aspects, bw, bh, gap=10)
            assert len(rects) == len(aspects)
            for a, r in zip(aspects, rects):
                got = r.width() / r.height()
                assert abs(got - a) / a < 1e-6, f"distorted: {got:.4f} vs {a:.4f}"
                assert r.left() >= -1e-6 and r.top() >= -1e-6, r
                assert r.right() <= bw + 1e-6 and r.bottom() <= bh + 1e-6, r
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    inter = rects[i].intersected(rects[j])
                    assert inter.width() * inter.height() < 1e-6, "tiles overlap"
    print(f"PASS: {len(CASES) * len(BOXES)} layouts keep every aspect ratio, "
          f"fit their box and never overlap")


def test_shapes_pick_sensible_rows():
    # Wide video frames stack in a tall box; portrait covers pair up.
    v = mosaic_rects([VIDEO, VIDEO], 800, 760, gap=10)
    assert v[0].top() != v[1].top(), "two video frames in a tall box should stack"
    c = mosaic_rects([COVER] * 4, 800, 760, gap=10)
    assert len({round(r.top()) for r in c}) == 2, "four covers should form 2 rows"
    # Three video frames and a square card: a balanced two-row grid, not one
    # giant frame over three thumbnails.
    m = mosaic_rects([VIDEO, SQUARE, VIDEO, VIDEO], 692, 692, gap=10)
    areas = [r.width() * r.height() for r in m]
    assert min(areas) / max(areas) > 0.3, f"lopsided mosaic: {areas}"
    print("PASS: videos stack, covers form a 2x2, mixed folders stay balanced")


if __name__ == "__main__":
    test_undistorted_and_inside()
    test_shapes_pick_sensible_rows()
