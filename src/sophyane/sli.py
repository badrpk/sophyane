"""Sophyane Learning Intelligence (SLI).

A dependency-free SQLite experience store for validator-grounded execution
learning. SLI improves Sophyane's action selection; it does not modify model
weights or bypass execution safety gates.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

__version__ = "0.2.0"

DB_PATH = Path(
    os.environ.get(
        "SOPHYANE_SLI_DB",
        Path.home() / ".local/state/sophyane/sli.db",
    )
)

SOURCE_WEIGHTS = {
    "execution": 1.00,
    "validator": 0.95,
    "user_feedback": 0.90,
    "manual": 0.80,
    "seed": 0.60,
    "unknown": 0.35,
    "scanned_log": 0.15,
    "synthetic": 0.10,
}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path or DB_PATH).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target)
    db.row_factory = sqlite3.Row
    initialize(db)
    return db


def initialize(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT '',
            reward REAL NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0.5,
            elapsed_seconds REAL NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL DEFAULT 'unknown',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_action
            ON memories(action);
        CREATE INDEX IF NOT EXISTS idx_memories_source
            ON memories(source_type);

        CREATE TABLE IF NOT EXISTS learned_execution_traces (
            trace_id TEXT PRIMARY KEY,
            request TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            reward REAL NOT NULL,
            quality_reward REAL NOT NULL DEFAULT 0,
            failure_category TEXT NOT NULL DEFAULT '',
            quality_signals TEXT NOT NULL DEFAULT '[]',
            result TEXT NOT NULL DEFAULT '',
            elapsed_seconds REAL NOT NULL DEFAULT 0,
            workspace_before TEXT NOT NULL DEFAULT '{}',
            workspace_after TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        );
        """
    )
    columns = {
        str(row["name"])
        for row in db.execute("PRAGMA table_info(memories)").fetchall()
    }
    if "source_type" not in columns:
        db.execute(
            "ALTER TABLE memories ADD COLUMN source_type TEXT NOT NULL DEFAULT 'unknown'"
        )
    db.commit()


def _tokens(value: object) -> set[str]:
    return {
        token
        for token in "".join(
            character.lower() if character.isalnum() else " "
            for character in str(value or "")
        ).split()
        if len(token) > 1
    }


def _similarity(left: object, right: object) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def record(
    db: sqlite3.Connection,
    *,
    request: str,
    action: str,
    reward: float,
    state: str = "",
    result: str = "",
    confidence: float = 0.5,
    elapsed_seconds: float = 0.0,
    source_type: str = "unknown",
) -> int:
    source = source_type if source_type in SOURCE_WEIGHTS else "unknown"
    cursor = db.execute(
        """
        INSERT INTO memories(
            request, state, action, result, reward, confidence,
            elapsed_seconds, source_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(request), str(state), str(action), str(result),
            max(-1.0, min(1.0, float(reward))),
            max(0.0, min(1.0, float(confidence))),
            max(0.0, float(elapsed_seconds)), source, time.time(),
        ),
    )
    db.commit()
    return int(cursor.lastrowid)


def recommend_actions(
    db: sqlite3.Connection,
    *,
    request: str,
    state: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM memories ORDER BY created_at DESC LIMIT 2000"
    ).fetchall()
    by_action: dict[str, list[tuple[float, sqlite3.Row]]] = {}
    query = f"{request} {state}".strip()

    for row in rows:
        similarity = _similarity(query, f"{row['request']} {row['state']}")
        source_weight = SOURCE_WEIGHTS.get(str(row["source_type"]), 0.35)
        reward_factor = (float(row["reward"]) + 1.0) / 2.0
        confidence = float(row["confidence"])
        recency = 1.0 / (1.0 + max(0.0, time.time() - float(row["created_at"])) / 86400.0)
        score = source_weight * (
            0.50 * similarity
            + 0.25 * reward_factor
            + 0.15 * confidence
            + 0.10 * recency
        )
        by_action.setdefault(str(row["action"]), []).append((score, row))

    ranked: list[dict[str, Any]] = []
    for action, examples in by_action.items():
        examples.sort(key=lambda item: item[0], reverse=True)
        strongest = examples[:3]
        confidence = sum(item[0] for item in strongest) / len(strongest)
        best = strongest[0][1]
        ranked.append(
            {
                "action": action,
                "confidence": confidence,
                "best_example": str(best["request"]),
                "best_source": str(best["source_type"]),
                "attempts": len(examples),
            }
        )

    ranked.sort(key=lambda item: item["confidence"], reverse=True)
    return ranked[: max(1, int(limit))]


def stats(db: sqlite3.Connection) -> dict[str, Any]:
    aggregate = db.execute(
        """
        SELECT COUNT(*) AS attempts,
               COUNT(DISTINCT action) AS actions,
               SUM(CASE WHEN reward > 0 THEN 1 ELSE 0 END) AS positive,
               SUM(CASE WHEN reward < 0 THEN 1 ELSE 0 END) AS negative,
               COALESCE(AVG(reward), 0) AS average_reward,
               COALESCE(AVG(elapsed_seconds), 0) AS average_elapsed
        FROM memories
        """
    ).fetchone()
    sources = {
        str(row["source_type"]): int(row["n"])
        for row in db.execute(
            "SELECT source_type, COUNT(*) AS n FROM memories GROUP BY source_type"
        ).fetchall()
    }
    return {
        "database": str(DB_PATH),
        "learned_executions": int(aggregate["attempts"]),
        "distinct_actions": int(aggregate["actions"]),
        "positive_outcomes": int(aggregate["positive"] or 0),
        "negative_outcomes": int(aggregate["negative"] or 0),
        "average_reward": float(aggregate["average_reward"]),
        "average_elapsed": float(aggregate["average_elapsed"]),
        "sources": sources,
    }


def store_trace(db: sqlite3.Connection, payload: dict[str, Any]) -> None:
    db.execute(
        """
        INSERT OR REPLACE INTO learned_execution_traces(
            trace_id, request, action, status, reward, quality_reward,
            failure_category, quality_signals, result, elapsed_seconds,
            workspace_before, workspace_after, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(payload.get("trace_id") or ""),
            str(payload.get("request") or ""),
            str(payload.get("action") or "EXECUTE_STRUCTURED_TASK"),
            str(payload.get("status") or "unknown"),
            float(payload.get("reward") or 0.0),
            float(payload.get("quality_reward") or 0.0),
            str(payload.get("failure_category") or ""),
            json.dumps(payload.get("quality_signals") or [], ensure_ascii=False),
            str(payload.get("result") or ""),
            float(payload.get("elapsed_seconds") or 0.0),
            json.dumps(payload.get("workspace_before") or {}),
            json.dumps(payload.get("workspace_after") or {}),
            time.time(),
        ),
    )
    db.commit()
