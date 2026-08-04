
"""Discover capability signatures from store; write catalog."""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path
from sophyane.code_memory.store import ChunkStore
from sophyane.code_memory.contracts import infer_domain, infer_provides

def discover(limit: int = 0) -> dict:
    store = ChunkStore()
    by_cap: dict[str, list[str]] = defaultdict(list)
    domains = Counter()
    n = 0
    for cid, c in store.chunks.items():
        n += 1
        if limit and n > limit:
            break
        meta = dict(c.meta or {})
        if meta.get("exclude"):
            continue
        domain = meta.get("domain") or infer_domain(c.text or "", c.path or "")
        provides = list(meta.get("provides") or infer_provides(c.text or "", c.path or ""))
        domains[domain] += 1
        for p in provides:
            if len(by_cap[p]) < 25:
                by_cap[p].append(cid)
    catalog = {
        "chunk_count": len(store.ids),
        "domains": dict(domains.most_common()),
        "capabilities": {k: v for k, v in sorted(by_cap.items(), key=lambda kv: -len(kv[1]))},
    }
    out = Path.home() / ".local/share/sophyane/code_memory" / "capability_catalog.json"
    out.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return {"capabilities": len(by_cap), "domains": len(domains), "path": str(out)}

if __name__ == "__main__":
    print(discover())
