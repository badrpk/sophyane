"""Durable PostgreSQL + pgvector memory backend for Sophyane.

Design:
- additive; existing filesystem memory remains intact
- PostgreSQL failures never have to break the harness
- deterministic local 384-D embeddings require no cloud service
- callers can supply real embeddings later
- HNSW-backed vector retrieval when PostgreSQL is available
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_DIMENSIONS = int(
    os.environ.get(
        "SOPHYANE_MEMORY_DIMENSIONS",
        "384",
    )
)

_TOKEN = re.compile(
    r"[A-Za-z0-9_./:+-]+",
)


def _dsn() -> str:
    explicit = os.environ.get(
        "SOPHYANE_POSTGRES_DSN",
        "",
    ).strip()

    if explicit:
        return explicit

    prefix = os.environ.get(
        "PREFIX",
        "/data/data/com.termux/files/usr",
    )

    return (
        f"host={prefix}/tmp "
        "port=5432 "
        "dbname=sophyane"
    )


def _normalize(
    values: list[float],
) -> list[float]:
    magnitude = math.sqrt(
        sum(
            value * value
            for value in values
        )
    )

    if magnitude <= 0.0:
        return values

    return [
        value / magnitude
        for value in values
    ]


def local_embedding(
    text: str,
    *,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> list[float]:
    """Deterministic dependency-free feature-hash embedding.

    This is deliberately a local fallback, not a claim to be a trained
    semantic embedding model. A real embedding vector can be passed to
    remember() and search() when one is available.
    """
    vector = [
        0.0
        for _ in range(dimensions)
    ]

    tokens = [
        item.casefold()
        for item in _TOKEN.findall(
            str(text or "")
        )
    ]

    if not tokens:
        return vector

    # Include unigrams and adjacent token pairs. This gives useful local
    # similarity while remaining deterministic and offline.
    features: list[str] = list(tokens)

    features.extend(
        f"{left}::{right}"
        for left, right in zip(
            tokens,
            tokens[1:],
        )
    )

    for feature in features:
        digest = hashlib.blake2b(
            feature.encode(
                "utf-8",
                errors="ignore",
            ),
            digest_size=16,
        ).digest()

        index = int.from_bytes(
            digest[:8],
            "little",
        ) % dimensions

        sign = (
            1.0
            if digest[8] & 1
            else -1.0
        )

        vector[index] += sign

    return _normalize(vector)




def canonical_embedding(
    text: str,
    *,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> tuple[list[float], str, str]:
    """Use Sophyane's canonical embedding subsystem.

    Returns:
        vector,
        provider description,
        embedding version

    The original local feature-hash implementation remains
    the emergency fallback so PostgreSQL memory never becomes
    dependent on an optional ML package.
    """
    try:
        from sophyane.code_memory.embedder import (
            get_embedder,
        )

        embedder = get_embedder()

        raw = embedder.embed(
            str(text or "")
        )

        vector = [
            float(value)
            for value in raw
        ]

        if len(vector) != dimensions:
            raise ValueError(
                "Canonical embedding dimension mismatch: "
                f"expected {dimensions}, "
                f"got {len(vector)}"
            )

        description = str(
            getattr(
                embedder,
                "description",
                type(embedder).__name__,
            )
        )

        provider_lower = (
            description
            .strip()
            .lower()
        )

        if provider_lower.startswith(
            "gguf/llama.cpp/"
        ):
            embedding_version = str(
                getattr(
                    embedder,
                    "embedding_version",
                    "gguf-bge-v1",
                )
            )

        elif provider_lower.startswith(
            "hashing-fallback/"
        ):
            embedding_version = (
                "hashing-v1"
            )

        elif (
            "sentence-transformer"
            in provider_lower
            or
            "sentence_transformers"
            in provider_lower
        ):
            embedding_version = (
                "sentence-transformer-v1"
            )

        else:
            embedding_version = (
                "canonical-v1"
            )

        return (
            vector,
            description,
            embedding_version,
        )

    except Exception:
        return (
            local_embedding(
                text,
                dimensions=dimensions,
            ),
            "postgres-memory/local-feature-hash",
            "fallback-v1",
        )


def _vector_literal(
    values: Iterable[float],
) -> str:
    return (
        "["
        + ",".join(
            format(float(value), ".9g")
            for value in values
        )
        + "]"
    )


@dataclass(frozen=True)
class MemoryHit:
    memory_key: str
    namespace: str
    content: str
    metadata: dict[str, Any]
    distance: float


class PostgresMemory:
    def __init__(
        self,
        dsn: str | None = None,
        *,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        self.dsn = (
            str(dsn).strip()
            if dsn
            else _dsn()
        )

        self.dimensions = int(
            dimensions
        )

    def connect(self):
        import psycopg

        return psycopg.connect(
            self.dsn,
            connect_timeout=3,
        )

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE EXTENSION IF NOT EXISTS vector"
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS
                    sophyane_memory (
                        id BIGSERIAL PRIMARY KEY,
                        memory_key TEXT UNIQUE NOT NULL,
                        namespace TEXT NOT NULL
                            DEFAULT 'general',
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL
                            DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL
                            DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL
                            DEFAULT now()
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    sophyane_memory_namespace_idx
                    ON sophyane_memory(namespace)
                    """
                )

                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                    sophyane_vector_memory (
                        id BIGSERIAL PRIMARY KEY,
                        memory_key TEXT UNIQUE NOT NULL,
                        namespace TEXT NOT NULL
                            DEFAULT 'general',
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL
                            DEFAULT '{{}}'::jsonb,
                        embedding vector({self.dimensions}),
                        created_at TIMESTAMPTZ NOT NULL
                            DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL
                            DEFAULT now()
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    sophyane_vector_memory_namespace_idx
                    ON sophyane_vector_memory(namespace)
                    """
                )

                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    sophyane_vector_memory_hnsw_idx
                    ON sophyane_vector_memory
                    USING hnsw (
                        embedding vector_l2_ops
                    )
                    """
                )

            conn.commit()

    def remember(
        self,
        *,
        memory_key: str,
        namespace: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> None:
        key = str(
            memory_key
        ).strip()

        if not key:
            raise ValueError(
                "memory_key cannot be empty"
            )

        namespace = (
            str(namespace).strip()
            or "general"
        )

        content = str(content)

        metadata_value = dict(
            metadata or {}
        )

        if embedding is not None:
            vector = list(embedding)
            embedding_provider = "caller-supplied"
            embedding_version = "external-v1"
        else:
            (
                vector,
                embedding_provider,
                embedding_version,
            ) = canonical_embedding(
                content,
                dimensions=self.dimensions,
            )

        if len(vector) != self.dimensions:
            raise ValueError(
                "Embedding dimension mismatch: "
                f"expected {self.dimensions}, "
                f"got {len(vector)}"
            )

        vector_text = _vector_literal(
            vector
        )

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sophyane_memory (
                        memory_key,
                        namespace,
                        content,
                        metadata,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        now()
                    )
                    ON CONFLICT (memory_key)
                    DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """,
                    (
                        key,
                        namespace,
                        content,
                        json.dumps(
                            metadata_value,
                            ensure_ascii=False,
                        ),
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO sophyane_vector_memory (
                        memory_key,
                        namespace,
                        content,
                        metadata,
                        embedding,
                        embedding_provider,
                        embedding_dimensions,
                        embedding_version,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s::vector,
                        %s,
                        %s,
                        %s,
                        now()
                    )
                    ON CONFLICT (memory_key)
                    DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding,
                        embedding_provider =
                            EXCLUDED.embedding_provider,
                        embedding_dimensions =
                            EXCLUDED.embedding_dimensions,
                        embedding_version =
                            EXCLUDED.embedding_version,
                        updated_at = now()
                    """,
                    (
                        key,
                        namespace,
                        content,
                        json.dumps(
                            metadata_value,
                            ensure_ascii=False,
                        ),
                        vector_text,
                        embedding_provider,
                        self.dimensions,
                        embedding_version,
                    ),
                )

            conn.commit()

    def search(
        self,
        query: str,
        *,
        namespace: str | None = None,
        limit: int = 8,
        embedding: list[float] | None = None,
    ) -> list[MemoryHit]:
        limit = max(
            1,
            min(
                int(limit),
                50,
            ),
        )

        if embedding is not None:
            vector = list(embedding)
            query_provider = None
            query_version = None
        else:
            (
                vector,
                query_provider,
                query_version,
            ) = canonical_embedding(
                query,
                dimensions=self.dimensions,
            )

        if len(vector) != self.dimensions:
            raise ValueError(
                "Embedding dimension mismatch"
            )

        vector_text = _vector_literal(
            vector
        )

        with self.connect() as conn:
            with conn.cursor() as cur:

                # Never compare vectors originating from incompatible
                # embedding spaces. This is especially important because
                # canonical_embedding() deliberately has a dependency-free
                # emergency fallback.
                provenance_filter = (
                    query_provider is not None
                    and query_version is not None
                )

                if namespace and provenance_filter:
                    cur.execute(
                        """
                        SELECT
                            memory_key,
                            namespace,
                            content,
                            metadata,
                            embedding <-> %s::vector
                                AS distance
                        FROM sophyane_vector_memory
                        WHERE namespace = %s
                          AND embedding IS NOT NULL
                          AND embedding_provider = %s
                          AND embedding_version = %s
                          AND embedding_dimensions = %s
                        ORDER BY
                            embedding <-> %s::vector
                        LIMIT %s
                        """,
                        (
                            vector_text,
                            namespace,
                            query_provider,
                            query_version,
                            self.dimensions,
                            vector_text,
                            limit,
                        ),
                    )

                elif provenance_filter:
                    cur.execute(
                        """
                        SELECT
                            memory_key,
                            namespace,
                            content,
                            metadata,
                            embedding <-> %s::vector
                                AS distance
                        FROM sophyane_vector_memory
                        WHERE embedding IS NOT NULL
                          AND embedding_provider = %s
                          AND embedding_version = %s
                          AND embedding_dimensions = %s
                        ORDER BY
                            embedding <-> %s::vector
                        LIMIT %s
                        """,
                        (
                            vector_text,
                            query_provider,
                            query_version,
                            self.dimensions,
                            vector_text,
                            limit,
                        ),
                    )

                elif namespace:
                    # Explicit external embeddings have no provider
                    # provenance, so preserve the existing caller-supplied
                    # vector behavior.
                    cur.execute(
                        """
                        SELECT
                            memory_key,
                            namespace,
                            content,
                            metadata,
                            embedding <-> %s::vector
                                AS distance
                        FROM sophyane_vector_memory
                        WHERE namespace = %s
                          AND embedding IS NOT NULL
                        ORDER BY
                            embedding <-> %s::vector
                        LIMIT %s
                        """,
                        (
                            vector_text,
                            namespace,
                            vector_text,
                            limit,
                        ),
                    )

                else:
                    cur.execute(
                        """
                        SELECT
                            memory_key,
                            namespace,
                            content,
                            metadata,
                            embedding <-> %s::vector
                                AS distance
                        FROM sophyane_vector_memory
                        WHERE embedding IS NOT NULL
                        ORDER BY
                            embedding <-> %s::vector
                        LIMIT %s
                        """,
                        (
                            vector_text,
                            vector_text,
                            limit,
                        ),
                    )

                rows = cur.fetchall()

        return [
            MemoryHit(
                memory_key=str(row[0]),
                namespace=str(row[1]),
                content=str(row[2]),
                metadata=(
                    row[3]
                    if isinstance(
                        row[3],
                        dict,
                    )
                    else {}
                ),
                distance=float(row[4]),
            )
            for row in rows
        ]

    def get(
        self,
        memory_key: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        memory_key,
                        namespace,
                        content,
                        metadata,
                        created_at,
                        updated_at
                    FROM sophyane_memory
                    WHERE memory_key = %s
                    """,
                    (
                        str(memory_key),
                    ),
                )

                row = cur.fetchone()

        if row is None:
            return None

        return {
            "memory_key": row[0],
            "namespace": row[1],
            "content": row[2],
            "metadata": (
                row[3]
                if isinstance(
                    row[3],
                    dict,
                )
                else {}
            ),
            "created_at": str(
                row[4]
            ),
            "updated_at": str(
                row[5]
            ),
        }

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM sophyane_memory
                    """
                )

                ordinary = int(
                    cur.fetchone()[0]
                )

                cur.execute(
                    """
                    SELECT count(*)
                    FROM sophyane_vector_memory
                    """
                )

                vectors = int(
                    cur.fetchone()[0]
                )

                cur.execute(
                    """
                    SELECT extversion
                    FROM pg_extension
                    WHERE extname = 'vector'
                    """
                )

                row = cur.fetchone()

        return {
            "ok": True,
            "backend": "postgres-pgvector",
            "database": "sophyane",
            "dimensions": self.dimensions,
            "memories": ordinary,
            "vector_memories": vectors,
            "pgvector_version": (
                str(row[0])
                if row
                else ""
            ),
        }

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()

        try:
            stats = self.stats()

            stats["latency_ms"] = round(
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0,
                2,
            )

            return stats

        except Exception as exc:
            return {
                "ok": False,
                "backend": "postgres-pgvector",
                "error": str(exc),
            }


_MEMORY: PostgresMemory | None = None


def get_postgres_memory() -> PostgresMemory:
    global _MEMORY

    if _MEMORY is None:
        _MEMORY = PostgresMemory()

    return _MEMORY
