from __future__ import annotations
import hashlib, os, re
from typing import Iterable
import numpy as np
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|[0-9]+")

def _tokenize(text: str):
    return [t.lower() for t in _TOKEN.findall(text or "")]

class HashingEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim
    def embed(self, text: str):
        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in _tokenize(text):
            h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec /= n
        return vec
    def embed_many(self, texts: Iterable[str]):
        seq = list(texts)
        if not seq:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.embed(t) for t in seq])

def get_embedder():
    return HashingEmbedder(384)
