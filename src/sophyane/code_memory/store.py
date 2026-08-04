from __future__ import annotations
import json, os, time, uuid
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
    return Path(os.environ.get("SOPHYANE_HOME", Path.home() / ".local/share/sophyane")).expanduser()

def memory_dir() -> Path:
    d = _home() / "code_memory"
    d.mkdir(parents=True, exist_ok=True)
    return d

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
        self._load()

    def _load(self) -> None:
        if self.meta_path.exists():
            for line in self.meta_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    c = CodeChunk(**d)
                    self.chunks[c.id] = c
                except Exception:
                    continue
        if self.ids_path.exists():
            try:
                self.ids = json.loads(self.ids_path.read_text(encoding="utf-8"))
            except Exception:
                self.ids = list(self.chunks.keys())
        else:
            self.ids = list(self.chunks.keys())
        if self.vec_path.exists():
            self.vectors = np.load(self.vec_path)
        if self.weight_path.exists():
            self.weights = np.load(self.weight_path)
        n = len(self.ids)
        if self.vectors is not None and len(self.vectors) != n:
            self.vectors = None
        if self.weights is not None and len(self.weights) != n:
            self.weights = None
        if self.vectors is None and n:
            texts = [self.chunks[i].text for i in self.ids if i in self.chunks]
            self.ids = [i for i in self.ids if i in self.chunks]
            self.vectors = self.embedder.embed_many(texts)
            self._save_vectors()
        if self.weights is None and self.ids:
            self.weights = np.array([self.chunks[i].weight for i in self.ids], dtype=np.float32)
            self._save_weights()

    def _save_meta_line(self, chunk: CodeChunk) -> None:
        with self.meta_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    def _save_ids(self) -> None:
        self.ids_path.write_text(json.dumps(self.ids), encoding="utf-8")

    def _save_vectors(self) -> None:
        if self.vectors is not None:
            np.save(self.vec_path, self.vectors)

    def _save_weights(self) -> None:
        if self.weights is not None:
            np.save(self.weight_path, self.weights)

    def add_chunk(self, text: str, **kwargs) -> CodeChunk:
        cid = uuid.uuid4().hex[:16]
        chunk = CodeChunk(
            id=cid,
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
        vec = self.embedder.embed(text)
        self.chunks[cid] = chunk
        self.ids.append(cid)
        if self.vectors is None or len(self.vectors) == 0:
            self.vectors = vec.reshape(1, -1)
        else:
            self.vectors = np.vstack([self.vectors, vec])
        if self.weights is None or len(self.weights) == 0:
            self.weights = np.array([chunk.weight], dtype=np.float32)
        else:
            self.weights = np.append(self.weights, np.float32(chunk.weight))
        self._save_meta_line(chunk)
        self._save_ids()
        self._save_vectors()
        self._save_weights()
        return chunk

    
    def _rewrite_meta(self) -> None:
        """Rewrite chunks.jsonl from in-memory chunks so weights stay visible."""
        tmp = self.meta_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for cid in self.ids:
                chunk = self.chunks.get(cid)
                if chunk is None:
                    continue
                f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
        tmp.replace(self.meta_path)

    def update_weight(self, chunk_id: str, new_weight: float) -> None:
        if chunk_id not in self.chunks:
            return
        self.chunks[chunk_id].weight = float(new_weight)
        try:
            idx = self.ids.index(chunk_id)
        except ValueError:
            return
        if self.weights is not None and idx < len(self.weights):
            self.weights[idx] = np.float32(new_weight)
            self._save_weights()
        # keep JSONL metadata in sync for inspection / reload of .weight field
        try:
            self._rewrite_meta()
        except Exception:
            pass

    def retrieve(self, query: str, top_k: int = 5):
        if not self.ids or self.vectors is None or len(self.vectors) == 0:
            return []
        q = self.embedder.embed(query)
        sims = self.vectors @ q
        w = self.weights if self.weights is not None else np.ones(len(self.ids), dtype=np.float32)
        scores = sims * np.clip(w, 0.05, 10.0)
        k = min(top_k, len(self.ids))
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        out = []
        for i in idx:
            cid = self.ids[int(i)]
            chunk = self.chunks.get(cid)
            if chunk is not None:
                out.append((chunk, float(scores[int(i)])))
        return out
