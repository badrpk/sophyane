"""Reinforcement Learning from Execution Feedback (RLEF) Reward Engine for Sophyane v21.4.0.

Dynamically updates vector chunk weights based on deterministic compiler pass/fail exit codes.
"""
import sqlite3
from pathlib import Path
from typing import Any

class ExecutionRewardEngine:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (Path.home() / ".local" / "share" / "sophyane" / "code_memory" / "million_chunk_store.db")

    def process_reward(self, chunk_id: str, exit_code: int, pass_rate: float = 1.0) -> dict[str, Any]:
        """Apply dynamic reward (+0.25 on pass) or penalty (-0.15 on fail) to chunk weight."""
        if not self.db_path.exists():
            return {"ok": False, "error": "Database file not found"}

        delta_weight = 0.25 if exit_code == 0 else -0.15
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("UPDATE chunks SET weight = MAX(0.1, weight + ?) WHERE chunk_id = ?", (delta_weight, chunk_id))
            conn.commit()
            
            cursor.execute("SELECT weight FROM chunks WHERE chunk_id = ?", (chunk_id,))
            row = cursor.fetchone()
            new_weight = row[0] if row else 1.0
            
            return {
                "ok": True,
                "chunk_id": chunk_id,
                "exit_code": exit_code,
                "reward_applied": delta_weight,
                "new_weight": new_weight,
                "status": "REWARD_UPDATED"
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
