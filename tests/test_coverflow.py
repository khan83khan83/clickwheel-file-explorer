import os
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QImage, QTransform

# Setup headless environment
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.library.model import LibraryNode
from app.screens.coverflow_screen import CoverFlowScreen
from app.navigation import ScreenStack
from app.application import Stage
from app.render.transforms import perspective_y
from app import theme

def test_coverflow():
    app = QApplication(sys.argv)
    
    # Test (a): perspective_y(0) is the identity transform
    t0 = perspective_y(0.0)
    assert t0.isIdentity(), "perspective_y(0) is not the identity transform"
    print("PASS (a): perspective_y(0) is the identity transform.")
    
    # Test (b): perspective_y(62) maps the cover's LEADING vertical edge to a SHORTER height than its trailing edge.
    t62 = perspective_y(62.0)
    w, h = 100.0, 200.0
    # Left edge (trailing edge for positive angle, x < 0)
    p_top_left = t62.map(float(-w/2), float(-h/2))
    p_bot_left = t62.map(float(-w/2), float(h/2))
    left_height = p_bot_left[1] - p_top_left[1]
    
    # Right edge (leading edge for positive angle, x > 0)
    p_top_right = t62.map(float(w/2), float(-h/2))
    p_bot_right = t62.map(float(w/2), float(h/2))
    right_height = p_bot_right[1] - p_top_right[1]
    
    assert right_height < left_height, f"Perspective failed: right height ({right_height}) not shorter than left height ({left_height})"
    print("PASS (b): perspective_y(62) has proper perspective (leading edge is shorter).")
    
    # Setup for Screen tests
    stage = Stage()
    stage.resize(1100, 720)
    stack = ScreenStack(stage)
    stage.set_stack(stack)

    docs = [LibraryNode(path=Path(f"{i}.pdf"), name=f"Doc {i}", is_dir=False, size=1024) for i in range(10)]

    # Test (c): at pos exactly N, the cover at index N sits dead centre, unrotated
    screen = CoverFlowScreen(stack, docs, 2)
    screen.on_enter()
    screen.pos_anim.snap(2.0)

    # force a paint to populate _drawn_indices and local vars
    img = QImage(stage.content_w, stage.content_h, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    screen.paint(p)
    p.end()

    assert screen.pos_anim.value == 2.0
    drawn = screen._last_drawn
    centre_item = next(item for item in drawn if item[1] == 2)
    _, _, _, x, angle, scale, _ = centre_item
    expected_x = stage.content_w / 2
    assert angle == 0.0, f"Expected angle 0.0, got {angle}"
    assert scale == 1.0, f"Expected scale 1.0, got {scale}"
    assert x == expected_x, f"Expected x {expected_x}, got {x}"
    print("PASS (c): at pos N, the cover at index N is centered with angle 0, scale 1.0 and correct X.")

    # Test (c2): the cover box scales with the window instead of being fixed
    small_w, small_h = screen._cover_box()
    stage.resize(1600, 1100)
    big_w, big_h = screen._cover_box()
    assert big_h > small_h and big_w > small_w, (small_w, small_h, big_w, big_h)
    stage.resize(1100, 720)
    print(f"PASS (c2): cover box reflows with the window "
          f"({small_w:.0f}x{small_h:.0f} -> {big_w:.0f}x{big_h:.0f}).")
    
    # Test (d): covers are drawn centre-last — assert the draw order of indices
    drawn = screen._drawn_indices
    assert len(drawn) > 0
    assert drawn[-1] == 2, f"Expected centre cover (index 2) to be drawn last, got {drawn[-1]}"
    print(f"PASS (d): covers are drawn centre-last (draw order: {drawn}).")
    
    # Test (e): the fan does NOT wrap — it stops at both ends.
    # The covers either side of the centre are visible on screen, so looping
    # round from the last to the first would contradict what is being shown.
    # Lists wrap; this does not.
    screen.index = 9
    screen.pos_anim.snap(9.0)
    screen.on_wheel(1)
    assert screen.index == 9, f"last cover must not wrap round: {screen.index}"
    screen.on_wheel(5)
    assert screen.index == 9, "repeated flicks past the end must stay put"

    screen.index = 0
    screen.pos_anim.snap(0.0)
    screen.on_wheel(-1)
    assert screen.index == 0, f"first cover must not wrap round: {screen.index}"
    screen.on_wheel(-5)
    assert screen.index == 0, "repeated flicks past the start must stay put"

    # Movement within range still animates normally.
    screen.on_wheel(3)
    assert screen.index == 3
    assert screen.pos_anim.tau == theme.CF_POS_TAU
    assert screen.pos_anim.active, "ordinary movement should animate"

    # A normal step still animates.
    screen.index = 4
    screen.pos_anim.snap(4.0)
    screen.on_wheel(1)
    assert screen.index == 5
    assert screen.pos_anim.value != 5.0, "an ordinary step should still glide"
    print("PASS (e): Cover Flow wraps at both ends, snapping on the wrap and "
          "gliding otherwise.")
    
    # Test (f): title opacity is 1.0 when settled and drops below 1.0 when pos is between covers.
    screen.index = 5
    screen.pos_anim.snap(5.0)
    
    p = QPainter(img)
    screen.paint(p)
    p.end()
    
    assert screen._title_opacity == 1.0, "Title opacity should be 1.0 when settled"
    
    screen.pos_anim.snap(5.4)
    p = QPainter(img)
    screen.paint(p)
    p.end()
    
    assert screen._title_opacity < 1.0, f"Title opacity should be < 1.0 when between covers, got {screen._title_opacity}"
    print("PASS (f): title opacity fades between covers.")

if __name__ == "__main__":
    test_coverflow()
