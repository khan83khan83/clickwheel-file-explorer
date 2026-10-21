from dataclasses import dataclass, field
from pathlib import Path
import re
import hashlib

def clean_name(raw: str) -> str:
    s = raw
    # 1. Drop the .pdf extension
    if s.lower().endswith(".pdf"):
        s = s[:-4]
        
    # 2. Strip a leading bracketed series tag
    s = re.sub(r'^\s*\[[^\]]*\]\s*', '', s)
    
    # 3. Strip a leading index
    s = re.sub(r'^\s*\d{1,3}\s*[\.\)\-_]\s*', '', s)
    
    # 4. Remove any parenthesised group containing mirror-site noise, case-insensitive
    s = re.sub(r'\s*\([^)]*(?:z-lib|zlib|1lib|libgen|b-ok|anna\'?s?-archive)[^)]*\)', '', s, flags=re.I)
    
    # 5. Remove a trailing mirror suffix
    s = re.sub(r'\s*[-–—]\s*(?:libgen|z-lib|zlib|1lib|b-ok)[^\s]*\s*$', '', s, flags=re.I)
    
    # 6. Remove a trailing year/publisher group
    s = re.sub(r'\s*\((?:19|20)\d{2}[^)]*\)\s*$', '', s)
    
    # 7. Replace _ with a space; collapse runs of whitespace to one; strip(); then strip trailing - – — , and spaces.
    s = s.replace('_', ' ')
    s = re.sub(r'\s+', ' ', s)
    s = s.strip()
    s = s.rstrip('-–—, ')
    s = s.strip()
    
    # 8. If the result is empty, the meaningful text was inside the leading
    #    bracket that step 2 removed (e.g. "[TIME vol. 200 iss. 23-24] - (2022)
    #    - libgen.li"). Recover it before falling back to the raw stem.
    if not s:
        stem = Path(raw).stem if raw.lower().endswith(".pdf") else raw
        m = re.match(r'^\s*\[([^\]]+)\]', stem)
        if m and m.group(1).strip():
            s = re.sub(r'\s+', ' ', m.group(1).replace('_', ' ')).strip()
        else:
            s = stem

    return s

def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]

@dataclass
class LibraryNode:
    path: Path
    name: str                       # cleaned display name
    is_dir: bool
    parent: "LibraryNode | None" = None
    children: list["LibraryNode"] = field(default_factory=list)   # dirs
    docs:     list["LibraryNode"] = field(default_factory=list)   # pdfs
    size: int = 0                   # bytes, files only
    mtime: float = 0.0
    pages: int | None = None        # filled lazily by covers/document

    @property
    def doc_count_deep(self) -> int:
        count = len(self.docs)
        for child in self.children:
            count += child.doc_count_deep
        return count

    @property
    def cache_key(self) -> str:
        s = f"{self.path}|{self.size}|{int(self.mtime)}"
        return hashlib.sha1(s.encode('utf-8')).hexdigest()
