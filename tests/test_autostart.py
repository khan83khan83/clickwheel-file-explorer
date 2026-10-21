import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# A throwaway profile: these tests create and delete Startup shortcuts, and
# must never touch the real one that launches the app at sign-in.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ipodnav_autostart_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import autostart                                        # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent


def test_shortcut_lives_in_the_user_startup_folder():
    p = autostart.shortcut_path()
    assert p.name == "Clickwheel File Explorer.lnk"
    assert "Startup" in str(p), p
    # Must be inside the user's own profile: no machine-wide or admin scope.
    assert str(p).lower().startswith(os.environ["APPDATA"].lower()), p
    print(f"PASS (a): the shortcut is one file in the user profile ({p.name}).")


def test_enable_disable_round_trip():
    was = autostart.is_enabled()
    try:
        ok, msg = autostart.enable(PROJECT, PROJECT / "assets" / "icons" / "app.ico")
        assert ok, msg
        assert autostart.is_enabled(), "shortcut missing after enable()"
        assert autostart.shortcut_path().stat().st_size > 0, "empty shortcut"
        print(f"PASS (b): enable() creates a real shortcut — {msg}")

        ok, msg = autostart.disable()
        assert ok, msg
        assert not autostart.is_enabled(), "shortcut survived disable()"
        print("PASS (c): disable() removes it again, leaving nothing behind.")
    finally:
        # Leave the machine exactly as it was found.
        if was and not autostart.is_enabled():
            autostart.enable(PROJECT)
        elif not was and autostart.is_enabled():
            autostart.disable()


def test_disable_is_idempotent():
    was = autostart.is_enabled()
    try:
        autostart.disable()
        ok, _ = autostart.disable()          # second time, nothing to remove
        assert ok, "disabling twice should not be an error"
        print("PASS (d): disable() on an already-disabled app is a no-op.")
    finally:
        if was and not autostart.is_enabled():
            autostart.enable(PROJECT)


def test_shortcut_launches_in_background():
    """The whole point: signing in must not throw a window up.

    Read the .lnk back through the shell rather than scanning its bytes — it is
    a structured binary format and a naive string search misses the arguments.
    """
    was = autostart.is_enabled()
    try:
        ok, msg = autostart.enable(PROJECT)
        assert ok, msg
        info = autostart.read_shortcut()
        assert info, "could not read the shortcut back"

        assert "--background" in info["arguments"], (
            f"login would open a window; arguments were {info['arguments']!r}")
        assert "main.py" in info["arguments"], info["arguments"]
        assert info["target"].lower().endswith("pythonw.exe"), (
            f"should launch without a console; target was {info['target']!r}")
        assert Path(info["target"]).exists(), "target interpreter does not exist"
        assert Path(info["working_dir"]) == PROJECT, info["working_dir"]
        assert info["window_style"] == "7", (
            f"window style should be minimised, got {info['window_style']}")
        print(f"PASS (e): shortcut runs {Path(info['target']).name} "
              f"{info['arguments']} minimised — login stays silent.")
    finally:
        if not was:
            autostart.disable()


def test_reconcile_renames_legacy_shortcut_only_if_present():
    autostart.disable()
    legacy = autostart.startup_dir() / autostart.LEGACY_SHORTCUT_NAME
    assert autostart.reconcile(PROJECT) is None, "must never enable on its own"
    assert not autostart.is_enabled()

    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"old")                 # stands in for the iPodPDF.lnk
    msg = autostart.reconcile(PROJECT)
    assert msg and "renamed" in msg, msg
    assert autostart.is_enabled() and not legacy.exists()
    assert "--background" in autostart.read_shortcut()["arguments"]
    autostart.disable()
    print("PASS (f): an iPodPDF.lnk becomes 'Clickwheel File Explorer.lnk'; with neither, "
          "autostart stays off.")


if __name__ == "__main__":
    try:
        test_shortcut_lives_in_the_user_startup_folder()
        test_enable_disable_round_trip()
        test_disable_is_idempotent()
        test_shortcut_launches_in_background()
        test_reconcile_renames_legacy_shortcut_only_if_present()
    finally:
        shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
