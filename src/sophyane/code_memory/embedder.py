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


def _tokenize(text: str):
    return [token.lower() for token in _TOKEN.findall(text or "")]


def _normalise(vector) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(value))
    return value / norm if norm > 0 else value


class HashingEmbedder:
    """Deterministic emergency fallback when no transformer backend is ready."""

    def __init__(self, dim: int = 384):
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


class OllamaEmbedder:
    """Transformer embeddings through the existing local Ollama service."""

    def __init__(self, model: str, base_url: str | None = None):
        self.model = model
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        probe = self.embed("Sophyane embedding dimension probe")
        self.dim = int(probe.shape[0])
        self.description = f"ollama-transformer/{model}/{self.dim}d"

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    def embed(self, text: str):
        try:
            result = self._post("/api/embed", {"model": self.model, "input": text})
            vectors = result.get("embeddings") or []
            if vectors:
                return _normalise(vectors[0])
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            result = self._post("/api/embeddings", {"model": self.model, "prompt": text})
            vector = result.get("embedding")
            if vector:
                return _normalise(vector)
        raise RuntimeError(f"Ollama model {self.model!r} returned no embedding")

    def embed_many(self, texts: Iterable[str]):
        values = list(texts)
        if not values:
            return np.zeros((0, self.dim), dtype=np.float32)
        try:
            result = self._post("/api/embed", {"model": self.model, "input": values})
            vectors = result.get("embeddings") or []
            if len(vectors) == len(values):
                return np.vstack([_normalise(vector) for vector in vectors])
        except Exception:
            pass
        return np.vstack([self.embed(value) for value in values])


class SentenceTransformerEmbedder:
    """Optional in-process transformer backend when sentence-transformers exists."""

    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model
        self.model = SentenceTransformer(model)
        self.dim = int(self.model.get_sentence_embedding_dimension())
        self.description = f"sentence-transformer/{model}/{self.dim}d"

    def embed(self, text: str):
        return _normalise(self.model.encode(text, normalize_embeddings=True))

    def embed_many(self, texts: Iterable[str]):
        values = list(texts)
        if not values:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.asarray(
            self.model.encode(values, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )


def _ollama_embedding_model() -> str | None:
    configured = str(os.environ.get("SOPHYANE_EMBED_MODEL") or "").strip()
    if configured:
        return configured

    host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    names = [str(item.get("name") or item.get("model") or "") for item in payload.get("models", [])]
    preferred = ("nomic-embed-text", "mxbai-embed-large", "bge-m3", "all-minilm")
    for prefix in preferred:
        for name in names:
            if name == prefix or name.startswith(prefix + ":"):
                return name
    return None


@lru_cache(maxsize=1)
def get_embedder():
    """Prefer a real transformer and preserve deterministic offline operation."""
    backend = str(os.environ.get("SOPHYANE_EMBED_BACKEND") or "auto").strip().lower()

    sentence_model = str(os.environ.get("SOPHYANE_SENTENCE_TRANSFORMER_MODEL") or "").strip()
    if backend in {"auto", "sentence-transformers", "sentence_transformers"} and sentence_model:
        try:
            return SentenceTransformerEmbedder(sentence_model)
        except Exception:
            if backend != "auto":
                raise

    if backend in {"auto", "ollama"}:
        model = _ollama_embedding_model()
        if model:
            try:
                return OllamaEmbedder(model)
            except Exception:
                if backend == "ollama":
                    raise

    return HashingEmbedder(int(os.environ.get("SOPHYANE_HASH_EMBED_DIM", "384")))
