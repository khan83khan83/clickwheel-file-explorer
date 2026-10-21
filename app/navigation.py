from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPainter, QColor
from app.animation import Animator

class ScreenStack(QObject):
    changed = Signal()
    
    def __init__(self, stage):
        super().__init__()
        self.stage = stage
        self.screens = []
        
        self.trans_anim = Animator(1.0)
        self.trans_anim.tau = 0.075
        self.trans_anim.epsilon = 0.004
        self.stage.register(self.trans_anim)
        
        # Root bump animator
        self.bump_anim = Animator(0.0)
        self.bump_anim.tau = 0.045
        self.bump_anim.epsilon = 0.2
        self.stage.register(self.bump_anim)
        
        self._old_screen = None
        self._is_push = True
        self.root_factory = None        # set by main: (LibraryNode) -> Screen
        self.library = None             # set by main: LibraryService

    @property
    def top(self) -> "Screen":
        if not self.screens:
            return None
        return self.screens[-1]

    @property
    def depth(self) -> int:
        return len(self.screens)
        
    @property
    def is_transitioning(self) -> bool:
        return self.trans_anim.active

    def push(self, screen: "Screen") -> None:
        if self.screens:
            self._old_screen = self.screens[-1]
            
        self.screens.append(screen)
        screen.on_enter()
        
        self._is_push = True
        self.trans_anim.snap(0.0)
        self.trans_anim.on_done = self._trans_done
        self.trans_anim.target(1.0)
        self.stage._ensure_timer()
        self.sync_watches()
        self.changed.emit()

    def pop(self) -> None:
        if len(self.screens) <= 1:
            return
            
        popped = self.screens.pop()
        popped.on_leave()
        
        self._old_screen = popped
        
        if self.top:
            self.top.on_enter()
        
        self._is_push = False
        self.trans_anim.snap(0.0)
        self.trans_anim.on_done = self._trans_done
        self.trans_anim.target(1.0)
        self.stage._ensure_timer()
        self.sync_watches()
        self.changed.emit()
        
    def _trans_done(self) -> None:
        self._old_screen = None

    # ------------------------------------------------------------- rescans

    def relist(self) -> None:
        """Re-read every open directory from disk, keeping the user in place.

        There is no whole-tree snapshot to diff against — directories are listed
        lazily — so each screen is rebuilt from its own path. Levels whose folder
        has since disappeared are dropped, leaving the nearest surviving ancestor
        on screen rather than a dead one.
        """
        chain = self.snapshot()
        if not chain:
            return
        self._rebuild(chain)

    # Kept as the old name so existing callers keep working.
    rebuild = relist

    def snapshot(self) -> list[dict]:
        """The open folders, root first, each with its cursor — JSON-ready, so it
        can be written to disk and handed back to restore() after a restart.
        Stops at the first screen that cannot be re-resolved from a path."""
        chain = []
        for s in self.screens:
            if s.library_path is None:
                break
            chain.append({"kind": type(s).__name__,
                          "path": str(s.library_path),
                          "cursor": self._cursor_of(s),
                          "top": getattr(s, "top", None)
                          if hasattr(s, "rows") else None})
        return chain

    def restore(self, chain) -> bool:
        """Reopen a saved snapshot, landing wherever it can: levels whose folder
        has gone are dropped. Returns False (leaving the stack untouched) if the
        chain is unusable, e.g. it was saved for a different library root."""
        if not chain or not self.screens:
            return False
        root = self.screens[0].library_path
        try:
            if root is None or Path(chain[0]["path"]) != Path(root):
                return False
            entries = [(c["kind"], c["path"], c.get("cursor"), c.get("top"))
                       for c in chain]
        except (KeyError, TypeError):
            return False
        self._rebuild(entries)
        return True

    def _rebuild(self, chain) -> None:
        from app.library.scanner import list_dir
        from app.screens.coverflow_screen import CoverFlowScreen
        from app.screens.menu_screen import MenuScreen

        if isinstance(chain[0], dict):
            chain = [(c["kind"], c["path"], c.get("cursor"), c.get("top"))
                     for c in chain]

        for s in self.screens:
            s.on_leave()
        self.screens.clear()

        for level, (kind, path, cursor, top) in enumerate(chain):
            if path is None or not Path(path).exists():
                break
            if level == 0 and self.root_factory:
                # The first page is the root menu with its pinned actions
                # (Refresh, Appearance, Quit); a plain listing would lose them.
                screen = self.root_factory()
            else:
                node = list_dir(Path(path))
                if kind == "CoverFlowScreen":
                    if not node.docs:
                        break
                    screen = CoverFlowScreen(self, node.docs)
                else:
                    screen = MenuScreen.from_node(self, node)
                    if screen is None:
                        break
            self.screens.append(screen)
            screen.on_enter()
            self._restore_cursor(screen, cursor, top)

        if not self.screens and self.root_factory:
            root = self.root_factory()
            self.screens.append(root)
            root.on_enter()

        self.trans_anim.snap(1.0)
        self._old_screen = None
        self.sync_watches()
        self.changed.emit()

    def sync_watches(self) -> None:
        """Watch exactly the directories currently open, and nothing else."""
        if self.library:
            self.library.watch([s.library_path for s in self.screens])

    @staticmethod
    def _cursor_of(screen):
        return getattr(screen, "sel", getattr(screen, "index", None))

    @staticmethod
    def _restore_cursor(screen, cursor, top=None) -> None:
        if cursor is None:
            return
        if hasattr(screen, "rows") and screen.rows:
            screen.sel = max(0, min(len(screen.rows) - 1, cursor))
            # Keep the saved scroll position, but never let it hide the
            # selection: the list may have changed length or the window size.
            vis = screen.visible_rows()
            t = screen.top if top is None else int(top)
            if screen.sel < t:
                t = screen.sel
            elif screen.sel >= t + vis:
                t = screen.sel - vis + 1
            screen.top = max(0, min(t, max(0, len(screen.rows) - vis)))
            screen.scroll_anim.snap(float(screen.top))
        elif hasattr(screen, "docs") and screen.docs:
            screen.index = max(0, min(len(screen.docs) - 1, cursor))
            screen.pos_anim.snap(float(screen.index))


    def bump(self) -> None:
        self.bump_anim.snap(0.0)
        self.bump_anim.on_done = self._bump_return
        self.bump_anim.target(7.0)
        self.stage._ensure_timer()
        
    def _bump_return(self) -> None:
        self.bump_anim.target(0.0)
        self.stage._ensure_timer()

    def paint_transition(self, p: QPainter) -> None:
        W = self.stage.content_w
        if self.bump_anim.value != 0:
            p.save()
            p.translate(self.bump_anim.value, 0)
            if self.top:
                self.top.paint(p)
            p.restore()
            return
            
        if not self.trans_anim.active or not self._old_screen:
            if self.top:
                self.top.paint(p)
            return
            
        t = self.trans_anim.value # 0 -> 1
        old = self._old_screen
        new = self.top
        
        H = self.stage.content_h
        if self._is_push:
            # old slides left
            p.save()
            p.translate(-t * W, 0)
            old.paint(p)
            p.fillRect(0, 0, W, H, QColor(0, 0, 0, int(60 * t)))
            p.restore()

            # new slides in from right
            p.save()
            p.translate((1 - t) * W, 0)
            new.paint(p)
            p.restore()
        else:
            # new slides in from left (it is at the bottom visually)
            p.save()
            p.translate((t - 1) * W, 0)
            new.paint(p)
            p.fillRect(0, 0, W, H, QColor(0, 0, 0, int(60 * (1 - t))))
            p.restore()

            # old slides right (it is on top visually)
            p.save()
            p.translate(t * W, 0)
            old.paint(p)
            p.restore()

class Screen(QObject):
    request_paint = Signal()
    
    def __init__(self, stack: ScreenStack):
        super().__init__()
        self.stack = stack

    @property
    def title(self) -> str:
        return ""

    def paint(self, p: QPainter) -> None:
        pass

    def on_wheel(self, steps: int) -> None:
        pass

    def on_left_click(self, x: float, y: float) -> None:
        pass

    def on_right_click(self, x: float, y: float) -> None:
        if self.stack.depth <= 1:
            self.stack.bump()
        else:
            self.stack.pop()

    def on_middle_click(self, x: float, y: float) -> None:
        pass

    def on_enter(self) -> None:
        pass

    def on_leave(self) -> None:
        pass

    @property
    def library_path(self):
        """Folder this screen represents, used to re-resolve it after a rescan.
        None means the screen cannot be restored and the stack stops there."""
        return None

    def on_scale_changed(self) -> None:
        """Window resized past the debounce. Screens holding bitmaps rendered at
        the old scale should re-request them here (§13.9)."""
        pass


def _find_node(root, path):
    """Locate the node for `path` in a freshly scanned tree."""
    target = Path(path)
    if Path(root.path) == target:
        return root
    for child in root.children:
        try:
            target.relative_to(Path(child.path))
        except ValueError:
            continue
        return _find_node(child, target)
    return None
