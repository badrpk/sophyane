from __future__ import annotations
from pathlib import Path
from sophyane.code_memory.store import ChunkStore
_LANG = {".py":"python",".js":"javascript",".html":"html",".css":"css",".ts":"typescript"}

def ingest_file(path: Path, store=None, source="ingest"):
    store = store or ChunkStore()
    path = path.expanduser().resolve()
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    if len(text) < 40 or len(text) > 250000:
        return 0
    store.add_chunk(text, language=_LANG.get(path.suffix.lower(),""), path=str(path), source=source, tags=[path.suffix.lower().lstrip(".")])
    return 1

def ingest_tree(root: Path, limit=50, source="ingest"):
    store = ChunkStore()
    n = 0
    for pattern in ("*.html","*.js","*.py","*.css"):
        for path in root.expanduser().rglob(pattern):
            if n >= limit:
                return n
            n += ingest_file(path, store, source=source)
    return n
