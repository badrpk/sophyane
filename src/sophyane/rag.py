"""Local document RAG (stdlib): ingest files, chunk, TF-IDF-ish retrieve."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

RAG_DIR = Path.home() / ".local" / "state" / "sophyane" / "rag"
INDEX_FILE = RAG_DIR / "index.jsonl"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())


def _chunk(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    while i < len(text):
        chunks.append(text[i : i + size])
        i += max(1, size - overlap)
    return chunks


def add_document(path: str | Path, *, source: str = "") -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    if path.stat().st_size > 5_000_000:
        return {"ok": False, "error": "file too large (5MB max)"}
    text = path.read_text(encoding="utf-8", errors="replace")
    return add_text(text, source=source or str(path), title=path.name)


def add_text(text: str, *, source: str = "inline", title: str = "") -> dict[str, Any]:
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    chunks = _chunk(text)
    n = 0
    with INDEX_FILE.open("a", encoding="utf-8") as handle:
        for i, ch in enumerate(chunks):
            doc = {
                "id": hashlib.sha256(f"{source}:{i}:{ch[:64]}".encode()).hexdigest()[:16],
                "source": source,
                "title": title or source,
                "chunk_index": i,
                "text": ch,
                "tf": dict(Counter(_tokenize(ch))),
                "ts": time.time(),
            }
            handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
            n += 1
    return {"ok": True, "chunks": n, "source": source}


def _load() -> list[dict[str, Any]]:
    if not INDEX_FILE.exists():
        return []
    docs: list[dict[str, Any]] = []
    for line in INDEX_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            docs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return docs


def query(q: str, *, top_k: int = 5) -> dict[str, Any]:
    docs = _load()
    q_tf = Counter(_tokenize(q))
    if not q_tf or not docs:
        return {"ok": True, "hits": [], "total_docs": len(docs)}
    # IDF
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set((d.get("tf") or {}).keys()))
    n = len(docs)
    scored: list[tuple[float, dict[str, Any]]] = []
    for d in docs:
        tf = d.get("tf") or {}
        score = 0.0
        for term, qf in q_tf.items():
            if term not in tf:
                continue
            idf = math.log((n + 1) / (1 + df.get(term, 0))) + 1.0
            score += qf * float(tf[term]) * idf
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [
        {
            "score": round(s, 4),
            "source": d.get("source"),
            "title": d.get("title"),
            "text": (d.get("text") or "")[:600],
            "id": d.get("id"),
        }
        for s, d in scored[: max(1, top_k)]
    ]
    return {"ok": True, "hits": hits, "total_docs": n, "query": q}


def rag_context(q: str, *, top_k: int = 4) -> str:
    res = query(q, top_k=top_k)
    if not res.get("hits"):
        return ""
    parts = ["# Retrieved knowledge"]
    for h in res["hits"]:
        parts.append(f"## {h.get('title')} ({h.get('source')})\n{h.get('text')}")
    return "\n\n".join(parts)


def status() -> dict[str, Any]:
    docs = _load()
    sources = sorted({d.get("source") for d in docs if d.get("source")})
    return {"ok": True, "chunks": len(docs), "sources": sources, "index": str(INDEX_FILE)}
