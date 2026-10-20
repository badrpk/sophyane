"""Durable SQLite audit ledger for consensus rounds."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import InvalidVote, ValidatedVote


class ConsensusLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._connection = sqlite3.connect(str(self.path), timeout=1.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 1000")
        try:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rounds (
                    round_id TEXT PRIMARY KEY,
                    workers_json TEXT NOT NULL,
                    quorum INTEGER NOT NULL,
                    base_commit TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id TEXT NOT NULL REFERENCES rounds(round_id),
                    worker_id TEXT,
                    status TEXT NOT NULL,
                    digest TEXT,
                    decision_json TEXT,
                    git_head TEXT,
                    failure_boundary TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS worker_locks (
                    worker_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    failure_boundary TEXT NOT NULL,
                    locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._connection.commit()
        except Exception:
            self._connection.close()
            raise

    def record_round(self, round_id: str, *, workers: list[str], quorum: int, base_commit: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO rounds(round_id, workers_json, quorum, base_commit) VALUES (?, ?, ?, ?)",
                (round_id, json.dumps(workers, separators=(",", ":")), quorum, base_commit),
            )

    def record_vote(self, round_id: str, vote: ValidatedVote | InvalidVote, *, status: str) -> None:
        decision = vote.decision if isinstance(vote, ValidatedVote) else None
        self._connection.execute(
            """INSERT INTO votes(round_id, worker_id, status, digest, decision_json, git_head,
               failure_boundary, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                round_id,
                vote.worker_id,
                status,
                vote.digest,
                json.dumps(decision, sort_keys=True, separators=(",", ":")) if decision is not None else None,
                vote.git_head,
                vote.failure_boundary,
                vote.error if isinstance(vote, InvalidVote) else None,
            ),
        )
        self._connection.commit()

    def lock_worker(self, worker_id: str, reason: str, failure_boundary: str) -> None:
        with self._connection:
            self._connection.execute(
                """INSERT INTO worker_locks(worker_id, reason, failure_boundary)
                   VALUES (?, ?, ?)
                   ON CONFLICT(worker_id) DO UPDATE SET reason=excluded.reason,
                   failure_boundary=excluded.failure_boundary, locked_at=CURRENT_TIMESTAMP""",
                (worker_id, reason, failure_boundary),
            )

    def is_locked(self, worker_id: str) -> bool:
        row = self._connection.execute("SELECT 1 FROM worker_locks WHERE worker_id = ?", (worker_id,)).fetchone()
        return row is not None

    def locked_workers(self) -> list[str]:
        rows = self._connection.execute("SELECT worker_id FROM worker_locks ORDER BY worker_id").fetchall()
        return [str(row["worker_id"]) for row in rows]

    def record_event(self, round_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO events(round_id, event_type, payload_json) VALUES (?, ?, ?)",
                (round_id, event_type, json.dumps(payload, sort_keys=True, separators=(",", ":"))),
            )

    def rounds(self) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT * FROM rounds ORDER BY created_at, round_id").fetchall()
        return [
            {"round_id": row["round_id"], "quorum": row["quorum"], "base_commit": row["base_commit"]}
            for row in rows
        ]

    def votes(self, round_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT * FROM votes WHERE round_id = ? ORDER BY id", (round_id,)).fetchall()
        return [dict(row) for row in rows]

    def events(self, round_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT * FROM events WHERE round_id = ? ORDER BY id", (round_id,)).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._connection.close()

