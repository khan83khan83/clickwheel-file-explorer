import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QImage                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import config                                           # noqa: E402
from app.library import preview, winthumb                        # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ROOT = Path(config.load_config()["library_root"])


def find(patterns):
    for pat in patterns:
        for p in ROOT.rglob(pat):
            return p
    return None


def test_kind_classification():
    assert preview.kind(Path("a.pdf")) == "pdf"
    assert preview.kind(Path("a.PDF")) == "pdf"
    assert preview.kind(Path("a.jpg")) == "image"
    assert preview.kind(Path("a.webp")) == "image"
    assert preview.kind(Path("a.mp4")) == "other"
    assert preview.kind(Path("a")) == "other"
    print("PASS (a): file kinds classify by extension, case-insensitively.")


def test_video_gets_a_real_thumbnail():
    vid = find(["*.mp4", "*.mkv", "*.mov", "*.avi"])
    if vid is None:
        print("SKIP (b): no video file in the library.")
        return
    img = winthumb.thumbnail(vid, 480)
    assert not img.isNull(), f"no shell thumbnail for {vid.name}"
    assert img.width() > 64 and img.height() > 64, (img.width(), img.height())

    # It must be a real frame, not a flat placeholder: sample a few pixels and
    # require some variation.
    colours = {img.pixel(x, y)
               for x in range(4, img.width(), max(1, img.width() // 8))
               for y in range(4, img.height(), max(1, img.height() // 8))}
    assert len(colours) > 4, f"thumbnail looks flat ({len(colours)} colours)"
    print(f"PASS (b): {vid.name[:38]!r} -> real {img.width()}x{img.height()} frame.")


def test_unpreviewable_file_falls_back_to_a_card():
    with tempfile.TemporaryDirectory() as td:
        txt = Path(td) / "notes.txt"
        txt.write_text("nothing to see", encoding="utf-8")

        assert winthumb.thumbnail(txt, 480).isNull(), (
            "plain text should have no shell thumbnail")

        img = preview.render_preview(txt, "notes.txt", 480)
        assert not img.isNull(), "fallback card must still produce an image"
        assert img.width() == 480, img.width()
        print("PASS (c): a file with no thumbnail provider falls back to a card.")


def test_render_preview_prefers_the_real_thing():
    vid = find(["*.mp4", "*.mkv", "*.mov"])
    if vid is None:
        print("SKIP (d): no video file in the library.")
        return
    real = winthumb.thumbnail(vid, 480)
    got = preview.render_preview(vid, vid.stem, 480)
    assert not got.isNull()
    assert (got.width(), got.height()) == (real.width(), real.height()), (
        "render_preview returned a drawn card instead of the shell thumbnail")
    print(f"PASS (d): render_preview uses the shell thumbnail "
          f"({got.width()}x{got.height()}), not the card.")


def test_thumbnail_is_safe_on_junk_input():
    missing = Path(r"D:\definitely\not\here\nope.mp4")
    assert winthumb.thumbnail(missing, 480).isNull()
    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "broken.mp4"
        broken.write_bytes(b"not a video")
        winthumb.thumbnail(broken, 480)          # must not raise
    print("PASS (e): missing and malformed files return null rather than raising.")


if __name__ == "__main__":
    test_kind_classification()
    test_video_gets_a_real_thumbnail()
    test_unpreviewable_file_falls_back_to_a_card()
    test_render_preview_prefers_the_real_thing()
    test_thumbnail_is_safe_on_junk_input()
