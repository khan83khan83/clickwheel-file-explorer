import os
import json
import copy
import sys
from pathlib import Path

# Module-level default
SCROLL_SPEED = 1.0

APP_NAME = "Clickwheel File Explorer"
DATA_DIR_NAME = "ClickwheelFileExplorer"
LEGACY_DIR_NAMES = ("iPodPDF", "iPodNavigator")  # oldest first; latest settings win

# Paths
def _roaming() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))

def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))

def get_appdata_dir() -> Path:
    return _roaming() / DATA_DIR_NAME

def get_localappdata_dir() -> Path:
    return _local() / DATA_DIR_NAME

MIGRATED_MARKER = ".migrated-from-iPodPDF"

def _move_into(src: Path, dst: Path) -> None:
    """Move src over dst. The legacy data is the user's real history, so it
    wins over anything a fresh start may already have written (defaults);
    directories such as the cover cache are merged entry by entry."""
    if src.is_dir() and dst.is_dir():
        for child in src.iterdir():
            _move_into(child, dst / child.name)
        src.rmdir()
    else:
        os.replace(src, dst)

def migrate_legacy_dirs() -> list[str]:
    """Carry settings, reading position and the cover cache over from the
    iPodPDF folders, once. Must run before anything opens a file in them.

    Keyed on a marker rather than on the new folder being absent: a test run
    or an earlier launch may already have created it with defaults inside."""
    moved = []
    for base in (_roaming(), _local()):
        for legacy_name in LEGACY_DIR_NAMES:
            old, new = base / legacy_name, base / DATA_DIR_NAME
            marker = new / f".migrated-from-{legacy_name}"
            if not old.is_dir() or marker.exists():
                continue
            try:
                new.mkdir(parents=True, exist_ok=True)
                for child in list(old.iterdir()):
                    _move_into(child, new / child.name)
                old.rmdir()
                marker.write_text("", encoding="utf-8")
                moved.append(f"{old} -> {new}")
            except OSError as e:
                moved.append(f"could not finish moving {old}: {e}")
    return moved

CONFIG_PATH = get_appdata_dir() / "config.json"
STATE_PATH = get_appdata_dir() / "state.json"
COVERS_DIR = get_localappdata_dir() / "covers"

DEFAULT_CONFIG = {
    "library_root": str(Path.home() / "Documents"),
    # Global hotkey that summons/dismisses the side panel. Any combination of
    # ctrl/alt/shift/win plus a key, e.g. "ctrl+alt+e" or "win+shift+p".
    # NOTE: this is claimed system-wide, so the chosen combination stops
    # reaching every other application while Clickwheel File Explorer is running.
    "hotkey": "ctrl+e",
    "panel_width": 420,
    # How far the docked panel is tinted from neutral grey toward the
    # Windows accent colour. 0 is flat grey, 0.3 is strongly accented.
    "panel_tint": 0.0,
    # Exact panel colour. Set by tools/sample_taskbar.py --apply, which reads
    # the real taskbar off the screen. null falls back to base + panel_tint.
    "panel_color": {"light": None, "dark": None},
    "panel_autohide": True,
    # Scrolling past either end of a list continues from the other end.
    "wrap": True,
    "theme": "classic_black",
    "click_sound": True,
    "scroll_speed": 1.0,
    "device_frame": False,
    "fullscreen": False,
    "window": {"w": 1280, "h": 960, "x": None, "y": None}
}

DEFAULT_STATE = {
    "recent": [],
    "progress": {}
}

CURRENT: dict = {}

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
        
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge with defaults to ensure all keys exist
            config = copy.deepcopy(DEFAULT_CONFIG)
            config.update(data)
            if "window" in data and isinstance(data["window"], dict):
                config["window"] = copy.deepcopy(DEFAULT_CONFIG["window"])
                config["window"].update(data["window"])
            return config
    except (ValueError, OSError):
        return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    os.replace(tmp_path, CONFIG_PATH)
    
def load_state() -> dict:
    if not STATE_PATH.exists():
        return copy.deepcopy(DEFAULT_STATE)
        
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            state = copy.deepcopy(DEFAULT_STATE)
            state.update(data)
            if "progress" in data and isinstance(data["progress"], dict):
                state["progress"] = copy.deepcopy(DEFAULT_STATE["progress"])
                state["progress"].update(data["progress"])
            return state
    except (ValueError, OSError):
        return copy.deepcopy(DEFAULT_STATE)

def save_state(state: dict) -> None:
    # Normalize paths in progress keys
    if "progress" in state:
        normalized_progress = {}
        for k, v in state["progress"].items():
            normalized_progress[str(Path(k).resolve())] = v
        state["progress"] = normalized_progress

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp_path, STATE_PATH)

def get(key: str, default=None):
    return CURRENT.get(key, default)

def set_value(key: str, value) -> None:
    CURRENT[key] = value
    save_config(CURRENT)

def init() -> None:
    global SCROLL_SPEED
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config()
    
    lib_root = config.get("library_root")
    if not lib_root or not Path(lib_root).exists():
        from PySide6.QtWidgets import QFileDialog, QApplication
        
        # Ensure we have a QApplication instance before using QFileDialog
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
            
        path = QFileDialog.getExistingDirectory(None, "Choose your PDF library folder")
        if path:
            config["library_root"] = str(Path(path).resolve())
            save_config(config)
        else:
            sys.exit(0)
            
    CURRENT.clear()
    CURRENT.update(config)
    SCROLL_SPEED = CURRENT.get("scroll_speed", 1.0)
