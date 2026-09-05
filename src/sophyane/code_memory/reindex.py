
"""Rebuild vectors/ids/weights from chunks.jsonl (coherent index)."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from sophyane.code_memory.embedder import get_embedder
from sophyane.config import DATA_DIR  # may fail; fallback below

def memory_dir() -> Path:
    return Path.home() / ".local/share/sophyane/code_memory"

def reindex() -> dict:
    mem = memory_dir()
    chunks_path = mem / "chunks.jsonl"
    records = []
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    embedder = get_embedder()
    ids, texts, weights = [], [], []
    for rec in records:
        cid = str(rec.get("id") or "")
        if not cid:
            continue
        ids.append(cid)
        texts.append(str(rec.get("text") or "")[:8000])
        weights.append(float(rec.get("weight") or 1.0))
    if not ids:
        return {"ids": 0}
    # Keep GGUF embedding requests bounded; a single request containing the
    # entire corpus can exceed llama.cpp request timeouts on mobile CPUs.
    try:
        batch_size = max(1, min(64, int(__import__("os").environ.get("SOPHYANE_REINDEX_BATCH", "16"))))
    except (TypeError, ValueError):
        batch_size = 16
    batches = [embedder.embed_many(texts[i:i + batch_size]) for i in range(0, len(texts), batch_size)]
    vecs = np.vstack(batches)
    np.save(mem / "vectors.npy", vecs)
    (mem / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    np.save(mem / "weights.npy", np.asarray(weights, dtype=np.float32))
    return {"ids": len(ids), "dim": int(vecs.shape[1]) if hasattr(vecs, "shape") else None}

if __name__ == "__main__":
    print(reindex())
