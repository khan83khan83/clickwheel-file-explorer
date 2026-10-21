"""Directory listing.

`list_dir` is lazy and reads one level at a time. An eager recursive walk was
fine for a folder of PDFs, but rooted at the Desktop it means ~10,000 files
across app installs and video folders — slow to scan, impossible to watch, and
almost all of it never looked at.
"""
import os
from pathlib import Path

from app.library.model import LibraryNode, clean_name, natural_key

SKIP_DIRS = {".git", "node_modules", "$recycle.bin",
             "system volume information", "__pycache__"}

# Noise that is never worth showing in a browser.
SKIP_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def _is_hidden(entry) -> bool:
    if entry.name.startswith("."):
        return True
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def _safe(entry, fn, default=False):
    try:
        return fn(entry)
    except OSError:
        return default


def list_dir(path: Path, parent: LibraryNode | None = None) -> LibraryNode:
    """One directory, non-recursively: every folder and every file.

    Folders land in `.children`, files in `.docs`, both natural-sorted. Never
    raises on an unreadable directory — it comes back empty instead.
    """
    path = Path(path)
    node = LibraryNode(path=path,
                       name=clean_name(path.name) or str(path),
                       is_dir=True, parent=parent)
    try:
        entries = list(os.scandir(path))
    except OSError:
        return node

    for entry in entries:
        try:
            if entry.is_symlink() or _safe(entry, lambda e: e.is_junction()):
                continue
            if _is_hidden(entry):
                continue

            if entry.is_dir():
                if entry.name.lower() in SKIP_DIRS:
                    continue
                node.children.append(LibraryNode(
                    path=Path(entry.path), name=clean_name(entry.name),
                    is_dir=True, parent=node))
            elif entry.is_file():
                if entry.name.lower() in SKIP_FILES:
                    continue
                st = entry.stat()
                node.docs.append(LibraryNode(
                    path=Path(entry.path), name=clean_name(entry.name),
                    is_dir=False, parent=node,
                    size=st.st_size, mtime=st.st_mtime))
        except OSError:
            continue                    # locked, or vanished mid-listing

    node.children.sort(key=lambda c: natural_key(c.name))
    node.docs.sort(key=lambda d: natural_key(d.name))
    return node


def scan(root: Path, max_depth: int = 8) -> LibraryNode:
    """Recursive walk, PDFs only, pruning branches that contain none.

    Kept for the tests and for anything that genuinely needs a whole tree; the
    browser itself uses `list_dir`.
    """
    root_node = LibraryNode(path=Path(root), name=clean_name(Path(root).name),
                            is_dir=True)
    _scan_recursive(root_node, max_depth)
    return root_node


def _scan_recursive(node: LibraryNode, depth: int) -> None:
    if depth < 0:
        return
    try:
        entries = list(os.scandir(node.path))
    except OSError:
        return

    for entry in entries:
        try:
            if entry.is_symlink() or _safe(entry, lambda e: e.is_junction()):
                continue
            if _is_hidden(entry):
                continue
            if entry.is_dir():
                if entry.name.lower() in SKIP_DIRS:
                    continue
                child = LibraryNode(path=Path(entry.path),
                                    name=clean_name(entry.name),
                                    is_dir=True, parent=node)
                _scan_recursive(child, depth - 1)
                if child.doc_count_deep > 0:
                    node.children.append(child)
            elif entry.is_file() and entry.name.lower().endswith(".pdf"):
                st = entry.stat()
                node.docs.append(LibraryNode(
                    path=Path(entry.path), name=clean_name(entry.name),
                    is_dir=False, parent=node, size=st.st_size, mtime=st.st_mtime))
        except OSError:
            continue

    node.children.sort(key=lambda c: natural_key(c.name))
    node.docs.sort(key=lambda d: natural_key(d.name))
