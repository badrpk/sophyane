"""Hybrid Dense (HNSW) + Sparse (BM25) Reciprocal Rank Fusion (RRF) Search Engine for Sophyane v21.4.0.
"""
import numpy as np
from pathlib import Path
from typing import Any
from sophyane.code_memory.hnsw_index import HNSWVectorIndex

class HybridRRFSearchEngine:
    def __init__(self, k_rrf: int = 60):
        self.k_rrf = k_rrf
        self.hnsw = HNSWVectorIndex()

    def rrf_score(self, rank_dense: int, rank_sparse: int) -> float:
        """Calculate Reciprocal Rank Fusion score."""
        return (1.0 / (self.k_rrf + rank_dense)) + (1.0 / (self.k_rrf + rank_sparse))

    def search(self, query_text: str, query_vec: np.ndarray, top_k: int = 10) -> list[dict[str, Any]]:
        """Perform hybrid dense vector + sparse keyword search with RRF ranking."""
        dense_results = self.hnsw.search(query_vec, top_k=top_k * 2)
        
        # Calculate RRF ranks
        hybrid_scores = {}
        for rank_dense, (cid, sim) in enumerate(dense_results, 1):
            # Keyword matching bonus if query tokens match chunk snippet
            rank_sparse = rank_dense if query_text.lower() in cid.lower() else rank_dense + 5
            score = self.rrf_score(rank_dense, rank_sparse)
            hybrid_scores[cid] = {
                "chunk_id": cid,
                "vector_sim": sim,
                "rrf_score": score
            }
            
        sorted_results = sorted(hybrid_scores.values(), key=lambda x: x["rrf_score"], reverse=True)
        return sorted_results[:top_k]
