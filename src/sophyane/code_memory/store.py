from __future__ import annotations

import json
import os
import tempfile
import time
import uuid

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sophyane.code_memory.embedder import get_embedder


@dataclass
class CodeChunk:
    id: str
    text: str
    language: str = ""
    path: str = ""
    license: str = "unknown"
    source: str = "seed"
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    weight: float = 1.0


def _home() -> Path:
    return Path(
        os.environ.get(
            "SOPHYANE_HOME",
            Path.home() / ".local/share/sophyane",
        )
    ).expanduser()


def memory_dir() -> Path:
    directory = _home() / "code_memory"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )

    temporary = Path(temporary_name)

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)

    finally:
        temporary.unlink(missing_ok=True)


def _atomic_numpy(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )

    temporary = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as handle:
            np.save(
                handle,
                value,
                allow_pickle=False,
            )

            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)

    finally:
        temporary.unlink(missing_ok=True)


class ChunkStore:
    def __init__(self) -> None:
        self.dir = memory_dir()
        self.meta_path = self.dir / "chunks.jsonl"
        self.vec_path = self.dir / "vectors.npy"
        self.weight_path = self.dir / "weights.npy"
        self.ids_path = self.dir / "ids.json"

        self.embedder = get_embedder()

        self.ids: list[str] = []
        self.chunks: dict[str, CodeChunk] = {}
        self.vectors = None
        self.weights = None

        self._batch_depth = 0
        self._dirty = False

        self._load()

    # ------------------------------------------------------------------
    # Loading and automatic index recovery
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self.meta_path.exists():
            try:
                lines = self.meta_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
            except OSError:
                lines = []

            for line in lines:
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                    chunk = CodeChunk(**record)
                except Exception:
                    continue

                self.chunks[chunk.id] = chunk

        if self.ids_path.exists():
            try:
                loaded = json.loads(
                    self.ids_path.read_text(
                        encoding="utf-8",
                    )
                )

                self.ids = [
                    str(chunk_id)
                    for chunk_id in loaded
                    if str(chunk_id) in self.chunks
                ]

            except Exception:
                self.ids = []

        if not self.ids:
            self.ids = list(self.chunks)

        self.vectors = self._safe_load_numpy(
            self.vec_path,
            "vectors",
        )

        self.weights = self._safe_load_numpy(
            self.weight_path,
            "weights",
        )

        expected = len(self.ids)

        if (
            self.vectors is not None
            and len(self.vectors) != expected
        ):
            self.vectors = None

        if (
            self.weights is not None
            and len(self.weights) != expected
        ):
            self.weights = None

        if self.vectors is None and self.ids:
            self.rebuild_index()
            return

        if self.weights is None and self.ids:
            self.weights = np.asarray(
                [
                    self.chunks[chunk_id].weight
                    for chunk_id in self.ids
                ],
                dtype=np.float32,
            )

            self._save_weights()

    def _safe_load_numpy(
        self,
        path: Path,
        label: str,
    ):
        if not path.exists():
            return None

        try:
            return np.load(
                path,
                allow_pickle=False,
            )

        except Exception as error:
            damaged = path.with_name(
                f"{path.name}.damaged-{int(time.time())}"
            )

            try:
                os.replace(path, damaged)
                print(
                    f"SLI memory: moved damaged {label} index "
                    f"to {damaged}",
                    flush=True,
                )
            except OSError:
                pass

            print(
                f"SLI memory: rebuilding {label} after "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

            return None

    # ------------------------------------------------------------------
    # Atomic persistence
    # ------------------------------------------------------------------

    def _save_ids(self) -> None:
        _atomic_text(
            self.ids_path,
            json.dumps(self.ids),
        )

    def _save_vectors(self) -> None:
        import os
        if os.environ.get('SOPHYANE_DEFER_VECTOR_SAVE') == '1':
            return
        if self.vectors is not None:
            _atomic_numpy(
                self.vec_path,
                np.asarray(
                    self.vectors,
                    dtype=np.float32,
                ),
            )

    def _save_weights(self) -> None:
        if self.weights is not None:
            _atomic_numpy(
                self.weight_path,
                np.asarray(
                    self.weights,
                    dtype=np.float32,
                ),
            )

    def _rewrite_meta(self) -> None:
        records = []

        for chunk_id in self.ids:
            chunk = self.chunks.get(chunk_id)

            if chunk is not None:
                records.append(
                    json.dumps(
                        asdict(chunk),
                        ensure_ascii=False,
                    )
                )

        _atomic_text(
            self.meta_path,
            "\n".join(records)
            + ("\n" if records else ""),
        )

    def flush(self) -> None:
        if not self._dirty:
            return

        self._rewrite_meta()
        self._save_ids()
        self._save_vectors()
        self._save_weights()

        self._dirty = False

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------

    def begin_batch(self) -> None:
        self._batch_depth += 1

    def end_batch(self) -> None:
        if self._batch_depth > 0:
            self._batch_depth -= 1

        if self._batch_depth == 0:
            self.flush()

    def __enter__(self):
        self.begin_batch()
        return self

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ):
        self.end_batch()
        return False

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def rebuild_index(self) -> None:
        self.ids = [
            chunk_id
            for chunk_id in self.ids
            if chunk_id in self.chunks
        ]

        if not self.ids:
            self.vectors = None
            self.weights = None
            self._dirty = True
            self.flush()
            return

        texts = [
            self.chunks[chunk_id].text
            for chunk_id in self.ids
        ]

        print(
            f"SLI memory: embedding {len(texts)} chunks",
            flush=True,
        )

        vectors = self.embedder.embed_many(texts)

        self.vectors = np.asarray(
            vectors,
            dtype=np.float32,
        )

        self.weights = np.asarray(
            [
                self.chunks[chunk_id].weight
                for chunk_id in self.ids
            ],
            dtype=np.float32,
        )

        self._dirty = True
        self.flush()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_chunk(
        self,
        text: str,
        **kwargs,
    ) -> CodeChunk:
        chunk_id = uuid.uuid4().hex[:16]

        chunk = CodeChunk(
            id=chunk_id,
            text=text,
            language=kwargs.get("language", ""),
            path=kwargs.get("path", ""),
            license=kwargs.get("license", "unknown"),
            source=kwargs.get("source", "seed"),
            tags=list(kwargs.get("tags") or []),
            meta=dict(kwargs.get("meta") or {}),
            created_at=time.time(),
            weight=float(kwargs.get("weight", 1.0)),
        )

        vector = np.asarray(
            self.embedder.embed(text),
            dtype=np.float32,
        )

        self.chunks[chunk_id] = chunk
        self.ids.append(chunk_id)

        if (
            self.vectors is None
            or len(self.vectors) == 0
        ):
            self.vectors = vector.reshape(1, -1)
        else:
            self.vectors = np.concatenate(
                [
                    self.vectors,
                    vector.reshape(1, -1),
                ],
                axis=0,
            )

        if (
            self.weights is None
            or len(self.weights) == 0
        ):
            self.weights = np.asarray(
                [chunk.weight],
                dtype=np.float32,
            )
        else:
            self.weights = np.concatenate(
                [
                    self.weights,
                    np.asarray(
                        [chunk.weight],
                        dtype=np.float32,
                    ),
                ]
            )

        self._dirty = True

        if self._batch_depth == 0:
            self.flush()

        return chunk

    def update_weight(
        self,
        chunk_id: str,
        new_weight: float,
    ) -> None:
        if chunk_id not in self.chunks:
            return

        self.chunks[chunk_id].weight = float(
            new_weight
        )

        try:
            index = self.ids.index(chunk_id)
        except ValueError:
            return

        if (
            self.weights is not None
            and index < len(self.weights)
        ):
            self.weights[index] = np.float32(
                new_weight
            )

        self._dirty = True

        if self._batch_depth == 0:
            self.flush()

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ):
        if (
            not self.ids
            or self.vectors is None
            or len(self.vectors) == 0
        ):
            return []

        vector = np.asarray(
            self.embedder.embed(query),
            dtype=np.float32,
        )

        scores = self.vectors @ vector

        weights = (
            self.weights
            if self.weights is not None
            else np.ones(
                len(self.ids),
                dtype=np.float32,
            )
        )

        scores = scores * np.clip(
            weights,
            0.05,
            10.0,
        )

        count = min(
            max(1, int(top_k)),
            len(self.ids),
        )

        indexes = np.argpartition(
            -scores,
            count - 1,
        )[:count]

        indexes = indexes[
            np.argsort(-scores[indexes])
        ]

        output = []

        for raw_index in indexes:
            index = int(raw_index)
            chunk_id = self.ids[index]
            chunk = self.chunks.get(chunk_id)

            if chunk is not None:
                output.append(
                    (
                        chunk,
                        float(scores[index]),
                    )
                )

        return output
