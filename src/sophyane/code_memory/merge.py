
"""Merge simple chunks into richer compound chunks (language-evolution style).

Simple chunks ≈ basic words.
Rich chunks ≈ complex words defined by multiple simpler ones.
Each rich chunk records:
  - parts: child chunk ids
  - inputs / outputs: union + external ports only
  - text: concatenated/composed body
  - weight: derived from children then learned independently
"""
from __future__ import annotations

import time
from typing import Iterable
from sophyane.code_memory.store import ChunkStore, CodeChunk


def _ports(chunk: CodeChunk, key: str) -> list[dict]:
    return list((chunk.meta or {}).get(key) or [])


def _port_names(ports: list[dict]) -> set[str]:
    return {str(p.get("name")) for p in ports if p.get("name")}


def merge_chunks(
    store: ChunkStore,
    child_ids: list[str],
    *,
    name: str,
    tags: list[str] | None = None,
    placement: str = "compound",
) -> CodeChunk | None:
    children = [store.chunks[i] for i in child_ids if i in store.chunks]
    if len(children) < 2:
        return None

    # External inputs = inputs not satisfied by sibling outputs
    all_inputs = []
    all_outputs = []
    for c in children:
        all_inputs.extend(_ports(c, "inputs"))
        all_outputs.extend(_ports(c, "outputs"))
    provided = _port_names(all_outputs)
    external_inputs = [p for p in all_inputs if str(p.get("name")) not in provided]

    parts_text = []
    for c in children:
        parts_text.append(f"/* part:{c.id} path:{c.path} */\n{c.text}")
    text = f"/* RICH CHUNK: {name} */\n" + "\n\n".join(parts_text)

    avg_w = sum(c.weight for c in children) / len(children)
    lang = children[0].language
    rich = store.add_chunk(
        text,
        language=lang,
        path=f"compound::{name}",
        source="merge",
        tags=list(tags or []) + ["rich", "compound", name],
        weight=max(1.0, avg_w * 1.05),
        meta={
            "kind": "rich",
            "name": name,
            "parts": child_ids,
            "inputs": external_inputs,
            "outputs": all_outputs,
            "placement": placement,
            "checks": ["compound"],
            "defined_by": child_ids,  # like defining a rich word via simple words
            "merged_at": time.time(),
        },
    )
    return rich


def auto_merge_by_shared_tags(store: ChunkStore, *, min_parts: int = 2, max_merges: int = 20) -> list[str]:
    """Create richer chunks when multiple simple chunks share domain tags."""
    by_tag: dict[str, list[str]] = {}
    for cid, c in store.chunks.values() and store.chunks.items():
        if (c.meta or {}).get("kind") == "rich":
            continue
        for tag in (c.tags or []):
            if tag in {"python", "javascript", "html", "css", "module", "function", "text"}:
                continue
            by_tag.setdefault(tag, []).append(cid)

    created = []
    for tag, ids in sorted(by_tag.items(), key=lambda kv: -len(kv[1])):
        if len(created) >= max_merges:
            break
        uniq = []
        seen = set()
        for i in ids:
            if i not in seen:
                seen.add(i)
                uniq.append(i)
        if len(uniq) < min_parts:
            continue
        # merge up to 4 related simples into one rich word/chunk
        rich = merge_chunks(store, uniq[:4], name=f"{tag}_bundle", tags=[tag])
        if rich is not None:
            created.append(rich.id)
    return created


def describe_rich(store: ChunkStore, chunk_id: str) -> dict:
    c = store.chunks.get(chunk_id)
    if not c:
        return {}
    meta = c.meta or {}
    return {
        "id": c.id,
        "name": meta.get("name"),
        "parts": meta.get("parts") or meta.get("defined_by") or [],
        "inputs": meta.get("inputs"),
        "outputs": meta.get("outputs"),
        "weight": c.weight,
        "tags": c.tags,
    }
