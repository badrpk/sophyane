from __future__ import annotations
import json, time
from sophyane.code_memory.store import ChunkStore, memory_dir

def apply_outcome(store: ChunkStore, chunk_ids: list[str], *, success: bool, strength: float = 0.15) -> None:
    for cid in chunk_ids:
        chunk = store.chunks.get(cid)
        if chunk is None:
            continue
        w = chunk.weight
        if success:
            w = min(10.0, w * (1.0 + strength) + 0.05)
        else:
            w = max(0.05, w * (1.0 - strength))
        store.update_weight(cid, w)
    log = memory_dir() / "weight_events.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "chunk_ids": chunk_ids, "success": success, "strength": strength}) + "\n")
