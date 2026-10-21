"""Start with Windows.

Implemented as a shortcut in the user's own Startup folder rather than a
registry Run entry: it is one file inside the user profile, it shows up in Task
Manager's Startup tab where it can be disabled like any other app, and undoing
it is deleting a file. No registry, no admin, nothing machine-wide.
"""
import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "Clickwheel File Explorer.lnk"
LEGACY_SHORTCUT_NAME = "iPodPDF.lnk"
LEGACY_SHORTCUT_NAMES = ("iPod Navigator.lnk", LEGACY_SHORTCUT_NAME)

CREATE_NO_WINDOW = 0x08000000


def startup_dir() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows"
            / "Start Menu" / "Programs" / "Startup")


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def is_enabled() -> bool:
    return shortcut_path().exists()


def is_frozen() -> bool:
    """Running as the packaged Clickwheel File Explorer.exe rather than from source."""
    return bool(getattr(sys, "frozen", False))


def _launch_spec(project_dir: Path) -> tuple[Path, str, Path]:
    """(target, arguments, working directory) for the Startup shortcut."""
    if is_frozen():
        exe = Path(sys.executable)
        return exe, "--background", exe.parent
    return _interpreter(), "main.py --background", project_dir


def _interpreter() -> Path:
    """pythonw.exe beside the running interpreter, so no console flashes."""
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return w
    return exe


def _run_powershell(script: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def enable(project_dir: Path, icon: Path | None = None) -> tuple[bool, str]:
    """Create the Startup shortcut. Returns (ok, message)."""
    if sys.platform != "win32":
        return False, "start with Windows is a Windows-only feature"

    target, args, workdir = _launch_spec(project_dir)
    lnk = shortcut_path()
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"cannot reach the Startup folder: {e}"

    icon_line = ""
    if icon and Path(icon).exists():
        icon_line = f"$s.IconLocation = '{icon}'\n"

    # WindowStyle 7 = minimised, so nothing flashes on sign-in. The app is
    # launched with --background and shows nothing until the hotkey is pressed.
    script = (
        f"$w = New-Object -ComObject WScript.Shell\n"
        f"$s = $w.CreateShortcut('{lnk}')\n"
        f"$s.TargetPath = '{target}'\n"
        f"$s.Arguments = '{args}'\n"
        f"$s.WorkingDirectory = '{workdir}'\n"
        f"$s.WindowStyle = 7\n"
        f"{icon_line}"
        f"$s.Description = 'Clickwheel File Explorer - press the hotkey to summon the panel'\n"
        f"$s.Save()\n"
    )
    ok, msg = _run_powershell(script)
    if not ok:
        return False, f"could not create the shortcut: {msg}"
    if not lnk.exists():
        return False, "the shortcut was not created"
    return True, f"will start with Windows ({lnk})"


def read_shortcut() -> dict:
    """What the Startup shortcut actually points at.

    A .lnk is a structured binary format, so scanning it for strings is
    unreliable — ask the shell to parse it instead. Returns {} if absent.
    """
    lnk = shortcut_path()
    if not lnk.exists():
        return {}
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}')\n"
        f"Write-Output $s.TargetPath\n"
        f"Write-Output $s.Arguments\n"
        f"Write-Output $s.WorkingDirectory\n"
        f"Write-Output $s.WindowStyle\n"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if len(lines) < 4:
        return {}
    return {"target": lines[0], "arguments": lines[1],
            "working_dir": lines[2], "window_style": lines[3]}


def disable() -> tuple[bool, str]:
    lnk = shortcut_path()
    if not lnk.exists():
        return True, "was not set to start with Windows"
    try:
        lnk.unlink()
    except OSError as e:
        return False, f"could not remove the shortcut: {e}"
    return True, "will no longer start with Windows"


def set_enabled(on: bool, project_dir: Path,
                icon: Path | None = None) -> tuple[bool, str]:
    return enable(project_dir, icon) if on else disable()


def reconcile(project_dir: Path, icon: Path | None = None) -> str | None:
    """Keep an existing start-with-Windows choice pointing at THIS copy.

    Never turns autostart on by itself. It only acts when the user had it on:
    a shortcut under the app's old name is replaced by one under the new
    name, and the packaged exe takes over a shortcut that still launches the
    source tree. Returns a log line, or None when nothing needed doing.
    """
    legacy_paths = [startup_dir() / name for name in LEGACY_SHORTCUT_NAMES]
    legacy_paths = [path for path in legacy_paths if path.exists()]
    if legacy_paths:
        ok, msg = enable(project_dir, icon)
        if ok:
            try:
                for legacy in legacy_paths:
                    legacy.unlink()
            except OSError as e:
                return f"autostart: new shortcut made, old one kept ({e})"
        return f"autostart: renamed from {legacy_paths[0].name} - {msg}"
    if is_frozen() and is_enabled():
        target = read_shortcut().get("target", "")
        if target and Path(target) != Path(sys.executable):
            ok, msg = enable(project_dir, icon)
            return f"autostart: repointed from {target} - {msg}"
    return None
