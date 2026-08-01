"""Durable, resumable mission execution for Sophyane."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sophyane.unified_execution_kernel import execute_request

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
MISSION_DB = STATE_DIR / "missions.sqlite3"


@dataclass(frozen=True)
class Mission:
    mission_id: str
    objective: str
    workspace: str
    status: str
    created_at: float
    updated_at: float
    max_steps: int
    completed_steps: int
    last_error: str


@dataclass(frozen=True)
class MissionStep:
    step_id: str
    mission_id: str
    sequence: int
    instruction: str
    status: str
    attempts: int
    result_json: str
    created_at: float
    updated_at: float


class MissionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or MISSION_DB).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    max_steps INTEGER NOT NULL,
                    completed_steps INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS mission_steps (
                    step_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    instruction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(mission_id)
                        REFERENCES missions(mission_id)
                        ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_sequence
                ON mission_steps(mission_id, sequence);
                """
            )
            connection.commit()

    def create(
        self,
        objective: str,
        steps: list[str],
        *,
        workspace: str | Path | None = None,
        max_steps: int = 50,
    ) -> Mission:
        if not objective.strip():
            raise ValueError("Mission objective cannot be empty.")

        cleaned = [step.strip() for step in steps if step.strip()]
        if not cleaned:
            raise ValueError("At least one mission step is required.")

        if len(cleaned) > max_steps:
            raise ValueError("Mission exceeds configured maximum steps.")

        root = Path(workspace or Path.cwd()).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        now = time.time()
        mission_id = f"mission-{uuid.uuid4().hex[:16]}"

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO missions(
                    mission_id, objective, workspace, status,
                    created_at, updated_at, max_steps, completed_steps
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, 0)
                """,
                (
                    mission_id,
                    objective.strip(),
                    str(root),
                    now,
                    now,
                    max_steps,
                ),
            )

            for sequence, instruction in enumerate(cleaned, start=1):
                connection.execute(
                    """
                    INSERT INTO mission_steps(
                        step_id, mission_id, sequence, instruction,
                        status, attempts, result_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', 0, '{}', ?, ?)
                    """,
                    (
                        f"step-{uuid.uuid4().hex[:16]}",
                        mission_id,
                        sequence,
                        instruction,
                        now,
                        now,
                    ),
                )

            connection.commit()

        mission = self.get(mission_id)
        if mission is None:
            raise RuntimeError("Mission was not persisted.")

        return mission

    def get(self, mission_id: str) -> Mission | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM missions WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()

        return Mission(**dict(row)) if row else None

    def steps(self, mission_id: str) -> list[MissionStep]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM mission_steps
                WHERE mission_id = ?
                ORDER BY sequence
                """,
                (mission_id,),
            ).fetchall()

        return [MissionStep(**dict(row)) for row in rows]

    def next_pending(self, mission_id: str) -> MissionStep | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM mission_steps
                WHERE mission_id = ? AND status IN ('pending', 'retry')
                ORDER BY sequence
                LIMIT 1
                """,
                (mission_id,),
            ).fetchone()

        return MissionStep(**dict(row)) if row else None

    def update_step(
        self,
        step_id: str,
        *,
        status: str,
        attempts: int,
        result: dict[str, Any],
    ) -> None:
        now = time.time()

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT mission_id FROM mission_steps
                WHERE step_id = ?
                """,
                (step_id,),
            ).fetchone()

            if not row:
                raise KeyError(step_id)

            mission_id = str(row["mission_id"])

            connection.execute(
                """
                UPDATE mission_steps
                SET status = ?, attempts = ?, result_json = ?, updated_at = ?
                WHERE step_id = ?
                """,
                (
                    status,
                    attempts,
                    json.dumps(result, ensure_ascii=False),
                    now,
                    step_id,
                ),
            )

            completed = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM mission_steps
                WHERE mission_id = ? AND status = 'completed'
                """,
                (mission_id,),
            ).fetchone()["count"]

            remaining = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM mission_steps
                WHERE mission_id = ?
                  AND status IN ('pending', 'retry', 'running')
                """,
                (mission_id,),
            ).fetchone()["count"]

            failed = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM mission_steps
                WHERE mission_id = ? AND status = 'failed'
                """,
                (mission_id,),
            ).fetchone()["count"]

            if failed:
                mission_status = "failed"
            elif remaining:
                mission_status = "running"
            else:
                mission_status = "completed"

            last_error = ""
            if status == "failed":
                last_error = str(
                    result.get("error")
                    or result.get("output")
                    or "Mission step failed."
                )[:4000]

            connection.execute(
                """
                UPDATE missions
                SET status = ?, completed_steps = ?, updated_at = ?,
                    last_error = ?
                WHERE mission_id = ?
                """,
                (
                    mission_status,
                    int(completed),
                    now,
                    last_error,
                    mission_id,
                ),
            )

            connection.commit()


def run_mission_step(
    mission_id: str,
    *,
    store: MissionStore | None = None,
    max_attempts: int = 2,
) -> dict[str, Any]:
    mission_store = store or MissionStore()
    mission = mission_store.get(mission_id)

    if mission is None:
        return {
            "ok": False,
            "mission_id": mission_id,
            "error": "mission_not_found",
        }

    step = mission_store.next_pending(mission_id)

    if step is None:
        return {
            "ok": mission.status == "completed",
            "mission": asdict(mission),
            "message": "No pending steps.",
        }

    attempts = step.attempts + 1

    mission_store.update_step(
        step.step_id,
        status="running",
        attempts=attempts,
        result={"message": "Execution started."},
    )

    result = execute_request(
        step.instruction,
        workspace=mission.workspace,
        request_id=step.step_id,
        metadata={"mission_id": mission_id},
    )

    if result is None:
        payload = {
            "ok": False,
            "error": "no_deterministic_capability",
            "instruction": step.instruction,
        }
        status = "failed" if attempts >= max_attempts else "retry"
    else:
        payload = result.to_dict()
        status = (
            "completed"
            if result.ok
            else ("failed" if attempts >= max_attempts else "retry")
        )

    mission_store.update_step(
        step.step_id,
        status=status,
        attempts=attempts,
        result=payload,
    )

    updated = mission_store.get(mission_id)

    return {
        "ok": status == "completed",
        "mission": asdict(updated) if updated else {},
        "step": asdict(step),
        "step_status": status,
        "result": payload,
    }


def run_mission(
    mission_id: str,
    *,
    store: MissionStore | None = None,
    max_iterations: int = 50,
) -> dict[str, Any]:
    mission_store = store or MissionStore()
    reports: list[dict[str, Any]] = []

    for _ in range(max(1, max_iterations)):
        mission = mission_store.get(mission_id)

        if mission is None:
            return {
                "ok": False,
                "mission_id": mission_id,
                "error": "mission_not_found",
            }

        if mission.status in {"completed", "failed", "cancelled"}:
            return {
                "ok": mission.status == "completed",
                "mission": asdict(mission),
                "steps": [
                    asdict(step)
                    for step in mission_store.steps(mission_id)
                ],
                "reports": reports,
            }

        report = run_mission_step(
            mission_id,
            store=mission_store,
        )
        reports.append(report)

    mission = mission_store.get(mission_id)

    return {
        "ok": False,
        "mission": asdict(mission) if mission else {},
        "steps": [
            asdict(step)
            for step in mission_store.steps(mission_id)
        ],
        "reports": reports,
        "error": "mission_iteration_limit_reached",
    }


__all__ = [
    "MISSION_DB",
    "Mission",
    "MissionStep",
    "MissionStore",
    "run_mission",
    "run_mission_step",
]
