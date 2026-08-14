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


def acquire_tree(
    root: Path,
    *,
    limit_files: int = 200,
    limit_chunks: int = 1000,
    source: str = "acquire",
    progress=None,
) -> dict:
    """Acquire source chunks into persistent memory in one batched transaction.

    The historical implementation used a second acquire_tree() wrapper that
    temporarily replaced ChunkStore with a subclass in module globals. The
    same behavior is now expressed directly: one store instance, explicit
    batch mode, deterministic flush, and post-flush durable memory reporting.
    """
    progress = (
        progress
        or (
            lambda _message:
                None
        )
    )

    root = Path(
        root
    ).expanduser().resolve()

    store = ChunkStore()

    existing = {
        (chunk.meta or {}).get(
            "fp"
        )
        for chunk in store.chunks.values()
        if (
            chunk.meta
            and (chunk.meta or {}).get(
                "fp"
            )
        )
    }

    files_n = 0
    chunks_n = 0
    skipped = 0

    store.begin_batch()

    try:
        for file_path in iter_source_files(
            root
        ):
            if (
                files_n >= limit_files
                or chunks_n >= limit_chunks
            ):
                break

            files_n += 1

            for raw in chunk_file(
                file_path
            ):
                if chunks_n >= limit_chunks:
                    break

                fp = _fp(
                    raw.text
                )

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

                existing.add(
                    fp
                )

                chunks_n += 1

            if (
                files_n % 25
                == 0
            ):
                progress(
                    "acquire: "
                    f"files={files_n} "
                    f"chunks={chunks_n} "
                    f"skipped={skipped}"
                )

    finally:
        # end_batch() flushes once depth reaches zero.
        while store._batch_depth > 0:
            store.end_batch()

    # Re-open the durable store rather than reporting the in-memory object.
    # This verifies that ids/chunks/vectors were actually persisted.
    durable_store = ChunkStore()

    report = {
        "root": str(
            root
        ),
        "files_scanned": files_n,
        "chunks_added": chunks_n,
        "skipped_dupes": skipped,
        "memory_size": len(
            durable_store.ids
        ),
        "ts": time.time(),
    }

    log = (
        Path(
            store.dir
        )
        / "acquire_events.jsonl"
    )

    with log.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(
                report
            )
            + "\n"
        )

    progress(
        f"acquire done: {report}"
    )

    return report
