
"""Down-weight failed families; boost successful chunk ids."""
from __future__ import annotations
from sophyane.code_memory.store import ChunkStore

BAN_PATH_PARTS = ("webxr", "polyfill", "todomvc", "bower_components", "execcommand")

def apply_harness_penalties() -> dict:
    store = ChunkStore()
    n_ban = 0
    for cid, c in list(store.chunks.items()):
        path = (c.path or "").lower()
        src = (c.source or "").lower()
        if any(b in path or b in src for b in BAN_PATH_PARTS):
            try:
                store.update_weight(cid, 0.03)
            except Exception:
                c.weight = 0.03
            meta = dict(c.meta or {})
            meta["exclude"] = True
            meta["domain"] = "vendor_demo"
            c.meta = meta
            store.chunks[cid] = c
            n_ban += 1
    if hasattr(store, "_rewrite_meta"):
        try:
            store._rewrite_meta()
        except Exception:
            pass
    return {"penalized": n_ban, "total": len(store.ids)}

if __name__ == "__main__":
    print(apply_harness_penalties())
