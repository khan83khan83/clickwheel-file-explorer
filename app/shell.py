"""Handing files to the OS."""
import os
import subprocess
import sys
from pathlib import Path

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _lucid_candidates() -> list[str]:
    """Where Lucid PDF Reader (the owner's PDF reader) is installed: per-user first, then per-machine."""
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        os.path.join(local, "Programs", "Lucid PDF Reader", "Lucid PDF Reader.exe") if local else "",
        r"C:\Program Files\Lucid PDF Reader\Lucid PDF Reader.exe",
    ]


def _lucid_path() -> str | None:
    for c in _lucid_candidates():
        if c and os.path.exists(c):
            return c
    return None


def _edge_path() -> str | None:
    for c in _EDGE_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def reveal(path: Path) -> bool:
    """Show a file or folder in Explorer, selecting it when it is a file."""
    path = Path(path)
    if not path.exists():
        return False
    if sys.platform != "win32":
        return open_pdf(path)
    try:
        if path.is_dir():
            subprocess.Popen(["explorer", str(path)], close_fds=True)
        else:
            # explorer wants this as ONE argument; a space after the comma breaks it.
            subprocess.Popen(f'explorer /select,"{path}"', close_fds=True)
        return True
    except OSError as e:
        print(f"reveal: {e}")
        return False


def open_file(path: Path) -> bool:
    """PDFs go to Lucid PDF Reader; everything else to whatever Windows associates."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return open_pdf(path)
    if not path.exists():
        print(f"open_file: missing {path}")
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))             # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)], close_fds=True)
        return True
    except OSError as e:
        print(f"open_file: could not open {path}: {e}")
        return False


def open_pdf(path: Path) -> bool:
    """Open a PDF in Lucid PDF Reader, falling back to the default handler, then Edge.

    Lucid is a single-instance app: when it is already running, the new launch hands the
    file to the open window. Returns True if something was launched.
    """
    path = Path(path)
    if not path.exists():
        print(f"open_pdf: missing {path}")
        return False

    lucid = _lucid_path()
    if lucid:
        try:
            subprocess.Popen([lucid, str(path)], close_fds=True)
            return True
        except OSError as e:
            print(f"open_pdf: Lucid PDF Reader failed ({e}); using default handler")

    try:
        if sys.platform == "win32":
            os.startfile(str(path))             # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)], close_fds=True)
        return True
    except OSError as e:
        print(f"open_pdf: default handler failed ({e}); trying Edge")

    edge = _edge_path()
    if edge:
        try:
            # --new-window: without it Edge appends a tab to its most recently used
            # window, which may sit on another virtual desktop and drag you there.
            subprocess.Popen([edge, "--new-window", str(path)], close_fds=True)
            return True
        except OSError as e:
            print(f"open_pdf: could not open {path}: {e}")
    return False
