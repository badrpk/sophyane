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
    """Prefer an in-process transformer and retain deterministic offline fallback."""
    backend = str(
        os.environ.get("SOPHYANE_EMBED_BACKEND")
        or "auto"
    ).strip().lower()

    sentence_model = str(
        os.environ.get("SOPHYANE_SENTENCE_TRANSFORMER_MODEL")
        or ""
    ).strip()

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
            return SentenceTransformerEmbedder(sentence_model)
        except Exception:
            if backend != "auto":
                raise

    return HashingEmbedder(TARGET_DIM)

