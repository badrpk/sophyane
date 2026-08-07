from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Iterable

import numpy as np

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|[0-9]+")
TARGET_DIM = int(os.environ.get("SOPHYANE_EMBED_DIM", "384"))


def _tokenize(text: str):
    return [token.lower() for token in _TOKEN.findall(text or "")]


def _normalise(vector) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(value))
    return value / norm if norm > 0 else value


def _project(vector, dim: int = TARGET_DIM) -> np.ndarray:
    """Deterministically fold transformer output into the stable SLI dimension."""
    source = _normalise(vector)
    if source.shape[0] == dim:
        return source
    target = np.zeros(dim, dtype=np.float32)
    for index, value in enumerate(source):
        bucket = index % dim
        target[bucket] += value if (index // dim) % 2 == 0 else -value
    return _normalise(target)


class HashingEmbedder:
    """Deterministic emergency fallback when no transformer backend is ready."""

    def __init__(self, dim: int = TARGET_DIM):
        self.dim = dim
        self.description = f"hashing-fallback/{dim}d"

    def embed(self, text: str):
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        return _normalise(vector)

    def embed_many(self, texts: Iterable[str]):
        values = list(texts)
        if not values:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.embed(value) for value in values])


class GGUFEmbeddingEmbedder:
    """Native llama.cpp embedding backend using a dedicated GGUF server.

    The server should be launched with llama-server --embedding using a
    dedicated embedding model. Native embedding dimensions are projected
    deterministically into Sophyane's stable TARGET_DIM vector space.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
    ):
        self.endpoint = (
            endpoint
            or os.environ.get(
                "SOPHYANE_GGUF_EMBED_ENDPOINT",
                "http://127.0.0.1:8768",
            )
        ).rstrip("/")

        self.model = (
            model
            or os.environ.get(
                "SOPHYANE_GGUF_EMBED_MODEL",
                "sophyane-embedding",
            )
        )

        self.dim = TARGET_DIM

        # Embedding-policy identity. Changing input normalization/truncation
        # changes the mathematical embedding function and therefore requires
        # a distinct vector-space version.
        self.embedding_version = (
            "gguf-bge-token500-v2"
        )

        try:
            configured_max_tokens = int(
                os.environ.get(
                    "SOPHYANE_GGUF_EMBED_MAX_TOKENS",
                    "500",
                )
            )
        except (TypeError, ValueError):
            configured_max_tokens = 500

        # Keep application input below the BGE 512-token context window.
        self.max_tokens = max(
            32,
            min(
                configured_max_tokens,
                500,
            ),
        )

        self.description = (
            f"gguf/llama.cpp/{self.model}"
            f"→{self.dim}d"
        )

    def _timeout(self) -> float:
        try:
            value = float(
                os.environ.get(
                    "SOPHYANE_GGUF_EMBED_TIMEOUT",
                    "60",
                )
            )
        except (TypeError, ValueError):
            value = 60.0

        return max(
            1.0,
            min(
                value,
                600.0,
            ),
        )

    def _token_count(
        self,
        text: str,
    ) -> int:
        """Count tokens using the exact active llama.cpp embedding model."""
        payload = json.dumps(
            {
                "content": str(text or ""),
                "add_special": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint + "/tokenize",
            data=payload,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout(),
            ) as response:
                body = json.loads(
                    response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                )

        except Exception as exc:
            raise RuntimeError(
                "GGUF tokenizer endpoint unavailable: "
                f"{exc}"
            ) from exc

        tokens = body.get(
            "tokens"
        )

        if not isinstance(
            tokens,
            list,
        ):
            raise RuntimeError(
                "GGUF tokenizer returned no token list"
            )

        return len(tokens)

    def _bounded_text(
        self,
        text: str,
    ) -> str:
        """Return the longest prefix fitting the canonical BGE token budget."""
        value = str(
            text or ""
        )

        if not value:
            return value

        if (
            self._token_count(
                value
            )
            <= self.max_tokens
        ):
            return value

        low = 0
        high = len(value)
        best = ""

        # Binary-search by character prefix, but validate every candidate
        # through llama.cpp's real tokenizer. Python string slicing preserves
        # Unicode code-point boundaries.
        while low <= high:
            midpoint = (
                low + high
            ) // 2

            candidate = value[
                :midpoint
            ]

            count = (
                self._token_count(
                    candidate
                )
            )

            if count <= self.max_tokens:
                best = candidate
                low = midpoint + 1
            else:
                high = midpoint - 1

        best = best.rstrip()

        if not best:
            raise RuntimeError(
                "Unable to construct bounded GGUF embedding input"
            )

        final_count = (
            self._token_count(
                best
            )
        )

        if final_count > self.max_tokens:
            raise RuntimeError(
                "GGUF embedding token bound was not enforced"
            )

        return best

    def _request(
        self,
        values: list[str],
    ) -> list[list[float]]:
        bounded_values = [
            self._bounded_text(
                str(value or "")
            )
            for value in values
        ]

        payload = json.dumps(
            {
                "model": self.model,
                "input": bounded_values,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint + "/v1/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        timeout = self._timeout()

        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                body = json.loads(
                    response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                )

        except Exception as exc:
            raise RuntimeError(
                "GGUF embedding endpoint unavailable: "
                f"{exc}"
            ) from exc

        data = body.get("data")

        if not isinstance(data, list):
            raise RuntimeError(
                "GGUF embedding endpoint returned "
                "no data array"
            )

        ordered = sorted(
            data,
            key=lambda item: int(
                item.get("index", 0)
            ),
        )

        vectors: list[list[float]] = []

        for item in ordered:
            raw = item.get("embedding")

            if not isinstance(raw, list):
                raise RuntimeError(
                    "GGUF embedding response contained "
                    "an invalid vector"
                )

            vectors.append(
                [
                    float(value)
                    for value in raw
                ]
            )

        if len(vectors) != len(values):
            raise RuntimeError(
                "GGUF embedding response count mismatch"
            )

        return vectors

    def embed(self, text: str):
        vectors = self._request(
            [str(text or "")]
        )

        return _project(
            vectors[0],
            self.dim,
        )

    def embed_many(self, texts: Iterable[str]):
        values = [
            str(value or "")
            for value in texts
        ]

        if not values:
            return np.zeros(
                (0, self.dim),
                dtype=np.float32,
            )

        vectors = self._request(values)

        return np.vstack(
            [
                _project(
                    vector,
                    self.dim,
                )
                for vector in vectors
            ]
        )



class SentenceTransformerEmbedder:
    """Optional in-process transformer backend when sentence-transformers exists."""

    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model
        self.model = SentenceTransformer(model)
        self.native_dim = int(self.model.get_sentence_embedding_dimension())
        self.dim = TARGET_DIM
        self.description = f"sentence-transformer/{model}/{self.native_dim}d→{self.dim}d"

    def embed(self, text: str):
        return _project(self.model.encode(text, normalize_embeddings=True), self.dim)

    def embed_many(self, texts: Iterable[str]):
        values = list(texts)
        if not values:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self.model.encode(values, normalize_embeddings=True, show_progress_bar=False)
        return np.vstack([_project(vector, self.dim) for vector in vectors])


def get_embedder():
    """Select Sophyane's canonical embedding backend.

    Priority is explicit configuration. In auto mode, a configured GGUF
    endpoint is preferred, then sentence-transformers, then deterministic
    hashing fallback.
    """
    backend = str(
        os.environ.get(
            "SOPHYANE_EMBED_BACKEND"
        )
        or "auto"
    ).strip().lower()

    sentence_model = str(
        os.environ.get(
            "SOPHYANE_SENTENCE_TRANSFORMER_MODEL"
        )
        or ""
    ).strip()

    gguf_endpoint = str(
        os.environ.get(
            "SOPHYANE_GGUF_EMBED_ENDPOINT"
        )
        or ""
    ).strip()

    gguf_model = str(
        os.environ.get(
            "SOPHYANE_GGUF_EMBED_MODEL"
        )
        or "sophyane-embedding"
    ).strip()

    if backend in {
        "gguf",
        "llama.cpp",
        "llama_cpp",
        "llamacpp",
    }:
        return GGUFEmbeddingEmbedder(
            endpoint=(
                gguf_endpoint
                or "http://127.0.0.1:8768"
            ),
            model=gguf_model,
        )

    if (
        backend == "auto"
        and gguf_endpoint
    ):
        try:
            embedder = GGUFEmbeddingEmbedder(
                endpoint=gguf_endpoint,
                model=gguf_model,
            )

            # Lightweight availability test. Failure falls through to the
            # existing local embedding mechanism.
            embedder.embed(
                "sophyane embedding health probe"
            )

            return embedder

        except Exception:
            pass

    if (
        backend
        in {
            "auto",
            "sentence-transformers",
            "sentence_transformers",
        }
        and sentence_model
    ):
        try:
            return SentenceTransformerEmbedder(
                sentence_model
            )

        except Exception:
            if backend != "auto":
                raise

    return HashingEmbedder(TARGET_DIM)

