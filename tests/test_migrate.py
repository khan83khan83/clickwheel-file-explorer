"""Renaming iPodPDF -> Clickwheel File Explorer keeps the user's settings, reading
position and cover cache — even when the new folders already exist with
defaults in them (a test run or a first launch can create them)."""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ipodnav_migrate_"))
os.environ["APPDATA"] = str(TMP / "Roaming")
os.environ["LOCALAPPDATA"] = str(TMP / "Local")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config                                           # noqa: E402


def test_old_data_wins_over_fresh_defaults_once():
    roam_old = TMP / "Roaming" / "iPodPDF"
    local_old = TMP / "Local" / "iPodPDF"
    (local_old / "covers").mkdir(parents=True)
    roam_old.mkdir(parents=True)
    (roam_old / "config.json").write_text(json.dumps({"hotkey": "alt+e"}))
    (roam_old / "state.json").write_text(json.dumps({"nav": ["real"]}))
    (local_old / "covers" / "a.jpg").write_bytes(b"old-a")
    (local_old / "app.log").write_text("old log\n")

    # What actually happened on this machine: the new folders already existed,
    # one holding a default state.json and a cover of its own.
    roam_new = TMP / "Roaming" / "ClickwheelFileExplorer"
    local_new = TMP / "Local" / "ClickwheelFileExplorer"
    (local_new / "covers").mkdir(parents=True)
    roam_new.mkdir(parents=True)
    (roam_new / "state.json").write_text(json.dumps({"nav": []}))
    (local_new / "covers" / "b.jpg").write_bytes(b"new-b")

    moved = config.migrate_legacy_dirs()
    assert len(moved) == 2 and all("->" in m for m in moved), moved
    assert not roam_old.exists() and not local_old.exists()
    assert json.loads((roam_new / "config.json").read_text())["hotkey"] == "alt+e"
    assert json.loads((roam_new / "state.json").read_text())["nav"] == ["real"]
    assert (local_new / "covers" / "a.jpg").read_bytes() == b"old-a"
    assert (local_new / "covers" / "b.jpg").read_bytes() == b"new-b"
    assert (local_new / "app.log").read_text() == "old log\n"

    # Once only: a later stray old folder must not clobber current settings.
    roam_old.mkdir()
    (roam_old / "config.json").write_text(json.dumps({"hotkey": "ctrl+e"}))
    assert config.migrate_legacy_dirs() == []
    assert json.loads((roam_new / "config.json").read_text())["hotkey"] == "alt+e"
    # The most recent installed name must migrate even when it carries the
    # marker from its own earlier rename, and it must win over older data.
    for base in (TMP / "Roaming", TMP / "Local"):
        previous = base / "iPodNavigator"
        previous.mkdir()
        (previous / ".migrated-from-iPodPDF").write_text("")
        (previous / "config.json").write_text(json.dumps({"hotkey": "win+e"}))
    assert len(config.migrate_legacy_dirs()) == 2
    assert json.loads((roam_new / "config.json").read_text())["hotkey"] == "win+e"
    assert config.migrate_legacy_dirs() == []
    print("PASS: old settings, position and covers move over fresh defaults, "
          "exactly once")


if __name__ == "__main__":
    test_old_data_wins_over_fresh_defaults_once()
