"""Reinforcement Learning from Execution Feedback (RLEF).

Apply deterministic execution rewards directly to the live ChunkStore so
successful and failed executions immediately influence semantic retrieval.
"""
from __future__ import annotations

from typing import Any

from sophyane.code_memory.store import ChunkStore


class ExecutionRewardEngine:
    """Update live code-memory weights from deterministic execution outcomes."""

    SUCCESS_DELTA = 0.25
    FAILURE_DELTA = -0.15
    MIN_WEIGHT = 0.1

    def __init__(self, store: ChunkStore | None = None):
        self.store = store or ChunkStore()

    def process_reward(
        self,
        chunk_id: str,
        exit_code: int,
        pass_rate: float = 1.0,
    ) -> dict[str, Any]:
        """Reward or penalize a live ChunkStore chunk.

        Successful execution applies +0.25. Failed execution applies -0.15,
        with a minimum persisted weight of 0.1. ``pass_rate`` remains in the
        public signature for compatibility with existing callers.
        """
        del pass_rate

        chunk = self.store.chunks.get(chunk_id)
        if chunk is None:
            return {
                "ok": False,
                "chunk_id": chunk_id,
                "exit_code": exit_code,
                "error": "Chunk not found in live ChunkStore",
            }

        delta_weight = (
            self.SUCCESS_DELTA
            if exit_code == 0
            else self.FAILURE_DELTA
        )

        old_weight = float(chunk.weight)
        new_weight = max(
            self.MIN_WEIGHT,
            old_weight + delta_weight,
        )

        try:
            self.store.update_weight(chunk_id, new_weight)
        except Exception as error:
            return {
                "ok": False,
                "chunk_id": chunk_id,
                "exit_code": exit_code,
                "error": str(error),
            }

        persisted = self.store.chunks.get(chunk_id)
        if persisted is None:
            return {
                "ok": False,
                "chunk_id": chunk_id,
                "exit_code": exit_code,
                "error": "Chunk disappeared after weight update",
            }

        return {
            "ok": True,
            "chunk_id": chunk_id,
            "exit_code": exit_code,
            "reward_applied": delta_weight,
            "old_weight": old_weight,
            "new_weight": float(persisted.weight),
            "status": "REWARD_UPDATED",
            "backend": "chunk_store",
        }
