from __future__ import annotations
from sophyane.code_memory.contracts import enrich_meta

"""Acquire code chunks from local trees into weighted memory."""

import hashlib
import json
import time
from pathlib import Path

from sophyane.code_memory.chunker import chunk_file, iter_source_files
from sophyane.code_memory.store import ChunkStore


def _fp(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", errors="ignore"), digest_size=16).hexdigest()


def acquire_tree(root: Path, *, limit_files: int = 200, limit_chunks: int = 1000, source: str = "acquire", progress=None) -> dict:
    progress = progress or (lambda m: None)
    store = ChunkStore()
    existing = {(c.meta or {}).get("fp") for c in store.chunks.values() if (c.meta or {}).get("fp")}
    files_n = chunks_n = skipped = 0
    for path in iter_source_files(root):
        if files_n >= limit_files or chunks_n >= limit_chunks:
            break
        files_n += 1
        for raw in chunk_file(path):
            if chunks_n >= limit_chunks:
                break
            fp = _fp(raw.text)
            if fp in existing:
                skipped += 1
                continue
            store.add_chunk(
                raw.text,
                language=raw.language,
                path=raw.path,
                source=source,
                tags=raw.tags,
                weight=1.0,
                meta={
                    "fp": fp,
                    "inputs": raw.inputs,
                    "outputs": raw.outputs,
                    "placement": raw.placement,
                    "checks": raw.checks,
                    "kind": "simple",
                    "acquired_at": time.time(),
                },
            )
            existing.add(fp)
            chunks_n += 1
        if files_n % 25 == 0:
            progress(f"acquire: files={files_n} chunks={chunks_n} skipped={skipped}")
    report = {
        "root": str(root),
        "files_scanned": files_n,
        "chunks_added": chunks_n,
        "skipped_dupes": skipped,
        "memory_size": len(ChunkStore().ids),
        "ts": time.time(),
    }
    log = Path(store.dir) / "acquire_events.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report) + "\n")
    progress(f"acquire done: {report}")
    return report


# --- SLI contract-on-ingest shim ---
_orig_add = None
try:
    from sophyane.code_memory.store import ChunkStore as _CS
    if not getattr(_CS.add_chunk, "_sli_contract_wrapped", False):
        _orig_add = _CS.add_chunk
        def _wrapped_add(self, text, *args, **kwargs):
            meta = dict(kwargs.get("meta") or {})
            path = str(kwargs.get("path") or "")
            from sophyane.code_memory.contracts import enrich_meta
            kwargs["meta"] = enrich_meta(meta, str(text or ""), path)
            if kwargs["meta"].get("exclude"):
                kwargs["weight"] = min(float(kwargs.get("weight") or 1.0), 0.05)
            return _orig_add(self, text, *args, **kwargs)
        _wrapped_add._sli_contract_wrapped = True
        _CS.add_chunk = _wrapped_add
except Exception:
    pass

# SOPHYANE_BATCH_ACQUIRE_V1
# The original acquisition logic is retained, but the ChunkStore constructor
# is temporarily wrapped so all add_chunk calls share one batch and write the
# full semantic index only once.

_acquire_tree_before_batch = acquire_tree


def acquire_tree(
    root,
    *,
    limit_files=200,
    limit_chunks=1000,
    source="acquire",
    progress=None,
):
    from sophyane.code_memory import store as _store_module

    original_class = _store_module.ChunkStore
    created = []

    class _BatchChunkStore(original_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.begin_batch()
            created.append(self)

    # acquire.py imported ChunkStore into its own global namespace.
    original_global = globals().get(
        "ChunkStore",
        original_class,
    )

    globals()["ChunkStore"] = _BatchChunkStore
    _store_module.ChunkStore = _BatchChunkStore

    try:
        return _acquire_tree_before_batch(
            root,
            limit_files=limit_files,
            limit_chunks=limit_chunks,
            source=source,
            progress=progress,
        )

    finally:
        for instance in created:
            try:
                while instance._batch_depth > 0:
                    instance.end_batch()
            except Exception as error:
                if progress:
                    progress(
                        "batch flush warning: "
                        f"{type(error).__name__}: {error}"
                    )

        globals()["ChunkStore"] = original_global
        _store_module.ChunkStore = original_class
