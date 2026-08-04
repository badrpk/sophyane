
"""Semantic retrieval: embedding similarity + role intent matching."""
from __future__ import annotations

from sophyane.code_memory.store import ChunkStore, CodeChunk
from sophyane.code_memory.semantics import semantic_score, infer_roles, classify_intent


def ensure_roles(store: ChunkStore, limit: int = 0) -> int:
    """Backfill roles into chunk meta for existing memory."""
    n = 0
    ids = list(store.ids)
    if limit:
        ids = ids[:limit]
    for cid in ids:
        c = store.chunks.get(cid)
        if c is None:
            continue
        meta = dict(c.meta or {})
        if meta.get("roles"):
            continue
        roles = infer_roles(c.text, c.path or "", c.tags)
        meta["roles"] = roles
        c.meta = meta
        store.chunks[cid] = c
        n += 1
    if n:
        # rewrite metadata snapshot if available
        if hasattr(store, "_rewrite_meta"):
            try:
                store._rewrite_meta()
            except Exception:
                pass
    return n


def retrieve_semantic(store: ChunkStore, message: str, top_k: int = 12) -> list[tuple[CodeChunk, float]]:
    intent = classify_intent(message)
    raw = store.retrieve(message, top_k=max(40, top_k * 4))
    ranked: list[tuple[CodeChunk, float]] = []
    for c, sim in raw:
        meta = dict(c.meta or {})
        if not meta.get("roles"):
            meta["roles"] = infer_roles(c.text, c.path or "", c.tags)
            c.meta = meta
        s = semantic_score(message, c, sim)
        # hard drop tests for non-general intents when not asked
        if "test" in (meta.get("roles") or []) and intent in {"browser_game", "web_app", "api"}:
            if "test" not in message.lower():
                continue
        ranked.append((c, s))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:top_k]
