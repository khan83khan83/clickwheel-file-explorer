"""Keeps the on-screen listing in step with the disk.

Only the directories currently open are watched — one per level of the
navigation stack. Watching the whole tree is not an option once the root is the
Desktop: that is ~10,000 files across app installs and video folders, far past
what QFileSystemWatcher can hold and almost all of it never displayed.
"""
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

# Filesystem events arrive in bursts (one copy fires several), so coalesce them.
DEBOUNCE_MS = 600


class LibraryService(QObject):
    changed = Signal()          # something under a watched directory moved

    def __init__(self, root_path: Path):
        super().__init__()
        self.root_path = Path(root_path)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self.changed.emit)

    def set_root(self, path: Path) -> None:
        self.root_path = Path(path)
        self.changed.emit()

    def watch(self, paths) -> None:
        """Watch exactly these directories, dropping any others."""
        wanted = {str(Path(p)) for p in paths if p and Path(p).is_dir()}
        current = set(self._watcher.directories())
        stale = current - wanted
        if stale:
            self._watcher.removePaths(list(stale))
        fresh = wanted - current
        if fresh:
            self._watcher.addPaths(list(fresh))

    def watched(self) -> list:
        return list(self._watcher.directories())

    def refresh(self) -> None:
        self.changed.emit()

    def _on_dir_changed(self, _path: str) -> None:
        self._debounce.start()
