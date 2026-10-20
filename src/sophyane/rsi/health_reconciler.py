"""Bounded health checks for repository-scoped RSI workers."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import sqlite3
import subprocess
import time


def _default_sampler(_node_id: str, _repository: Path) -> dict[str, int]:
    memory_bytes = 0
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        memory_bytes = pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError, TypeError):
        pass
    try:
        open_fds = len(os.listdir("/proc/self/fd"))
    except OSError:
        open_fds = -1
    return {"memory_bytes": memory_bytes, "open_fds": open_fds}


def _default_git_probe(repository: Path) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), "rev-parse", "HEAD"),
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git HEAD probe failed")
    return result.stdout.strip()


class HealthReconciler:
    """Persist node health and expose one bounded health tick."""

    def __init__(
        self,
        state_db: Path,
        *,
        ttl_seconds: float = 300,
        failure_threshold: int = 3,
        clock: Callable[[], float] = time.time,
        sampler: Callable[[str, Path], dict[str, int]] | None = None,
        git_probe: Callable[[Path], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or failure_threshold < 1:
            raise ValueError("health reconciler limits must be positive")
        self.state_db = Path(state_db)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = float(ttl_seconds)
        self.failure_threshold = int(failure_threshold)
        self.clock = clock
        self.sampler = sampler or _default_sampler
        self.git_probe = git_probe or _default_git_probe
        self._callbacks: dict[str, Callable[[], object]] = {}
        self._connection = sqlite3.connect(self.state_db, timeout=1.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=1000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                repository TEXT NOT NULL,
                expected_commit TEXT NOT NULL,
                last_heartbeat REAL NOT NULL,
                failure_streak INTEGER NOT NULL DEFAULT 0,
                last_status TEXT NOT NULL DEFAULT 'registered',
                last_failure_boundary TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                rollback_state TEXT NOT NULL DEFAULT 'not_needed'
            );
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                recorded_at REAL NOT NULL,
                memory_bytes INTEGER NOT NULL,
                open_fds INTEGER NOT NULL,
                live_commit TEXT NOT NULL,
                git_parity INTEGER NOT NULL,
                status TEXT NOT NULL,
                failure_boundary TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at REAL NOT NULL,
                node_id TEXT NOT NULL,
                event TEXT NOT NULL,
                boundary TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT ''
            );
            """
        )
        self._connection.commit()

    def register_node(
        self,
        node_id: str,
        repository: Path,
        expected_commit: str,
        rollback: Callable[[], object],
    ) -> None:
        node_id = str(node_id).strip()
        if not node_id or not str(expected_commit).strip() or not callable(rollback):
            raise ValueError("node registration requires an ID, commit, and rollback callback")
        now = float(self.clock())
        self._connection.execute(
            """
            INSERT INTO nodes(node_id, repository, expected_commit, last_heartbeat)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                repository=excluded.repository,
                expected_commit=excluded.expected_commit,
                last_heartbeat=excluded.last_heartbeat
            """,
            (node_id, str(Path(repository).resolve()), str(expected_commit).strip(), now),
        )
        self._connection.commit()
        self._callbacks[node_id] = rollback

    def heartbeat(self, node_id: str) -> None:
        cursor = self._connection.execute(
            "UPDATE nodes SET last_heartbeat = ? WHERE node_id = ?",
            (float(self.clock()), str(node_id)),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"unknown health node: {node_id}")
        self._connection.commit()

    def tick(self) -> dict[str, object]:
        now = float(self.clock())
        stale = self._connection.execute(
            "SELECT node_id FROM nodes WHERE ? - last_heartbeat > ? ORDER BY node_id",
            (now, self.ttl_seconds),
        ).fetchall()
        pruned = [row["node_id"] for row in stale]
        for node_id in pruned:
            self._connection.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
            self._callbacks.pop(node_id, None)
            self._connection.execute(
                "INSERT INTO audit_events(recorded_at, node_id, event, boundary, detail) VALUES (?, ?, ?, ?, ?)",
                (now, node_id, "worker_pruned", "heartbeat_ttl", f"older than {self.ttl_seconds}s"),
            )
        rows = self._connection.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()
        result: dict[str, object] = {"status": "healthy", "nodes": {}, "pruned": pruned}
        for row in rows:
            node = self._check_node(row, now)
            result["nodes"][row["node_id"]] = node
            if node["status"] != "healthy":
                result["status"] = "degraded"
        self._connection.commit()
        return result

    def _check_node(self, row: sqlite3.Row, now: float) -> dict[str, object]:
        node_id = row["node_id"]
        memory_bytes = 0
        open_fds = -1
        live_commit = ""
        boundary = ""
        error = ""
        try:
            sample = self.sampler(node_id, Path(row["repository"]))
            memory_bytes = int(sample["memory_bytes"])
            open_fds = int(sample["open_fds"])
        except Exception as exc:
            boundary, error = "metrics", f"{type(exc).__name__}: {exc}"
        if not boundary:
            try:
                live_commit = str(self.git_probe(Path(row["repository"])))
            except Exception as exc:
                boundary, error = "git_probe", f"{type(exc).__name__}: {exc}"
        parity = bool(live_commit and live_commit == row["expected_commit"])
        if not boundary and not parity:
            boundary, error = "git_head_parity", f"expected {row['expected_commit']}, got {live_commit or '<empty>'}"
        status = "healthy" if not boundary else "degraded"
        streak = 0 if status == "healthy" else int(row["failure_streak"]) + 1
        self._connection.execute(
            """
            INSERT INTO ticks(node_id, recorded_at, memory_bytes, open_fds, live_commit,
                              git_parity, status, failure_boundary, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (node_id, now, memory_bytes, open_fds, live_commit, int(parity), status, boundary, error),
        )
        self._connection.execute(
            "UPDATE nodes SET failure_streak=?, last_status=?, last_failure_boundary=?, last_error=? WHERE node_id=?",
            (streak, status, boundary, error, node_id),
        )
        if boundary:
            self._connection.execute(
                "INSERT INTO audit_events(recorded_at, node_id, event, boundary, detail) VALUES (?, ?, ?, ?, ?)",
                (now, node_id, "health_failure", boundary, error),
            )
        rollback_state = row["rollback_state"]
        if streak >= self.failure_threshold and rollback_state == "not_needed":
            callback = self._callbacks.get(node_id)
            try:
                if callback is None:
                    raise RuntimeError("rollback callback unavailable")
                callback()
                rollback_state = "rolled_back"
                event = "rollback_triggered"
                detail = "failure threshold reached"
            except Exception as exc:
                rollback_state = "rollback_failed"
                event = "rollback_failed"
                detail = f"{type(exc).__name__}: {exc}"
            self._connection.execute(
                "UPDATE nodes SET rollback_state=? WHERE node_id=?", (rollback_state, node_id)
            )
            self._connection.execute(
                "INSERT INTO audit_events(recorded_at, node_id, event, boundary, detail) VALUES (?, ?, ?, ?, ?)",
                (now, node_id, event, "rollback", detail),
            )
        return {
            "status": status,
            "memory_bytes": memory_bytes,
            "open_fds": open_fds,
            "live_commit": live_commit,
            "git_parity": parity,
            "failure_streak": streak,
            "failure_boundary": boundary,
            "error": error,
            "rollback_state": rollback_state,
        }

    def status(self) -> dict[str, object]:
        rows = self._connection.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()
        return {
            "nodes": {
                row["node_id"]: {
                    "repository": row["repository"],
                    "expected_commit": row["expected_commit"],
                    "last_heartbeat": row["last_heartbeat"],
                    "failure_streak": row["failure_streak"],
                    "status": row["last_status"],
                    "failure_boundary": row["last_failure_boundary"],
                    "rollback_state": row["rollback_state"],
                }
                for row in rows
            },
            "last_failure_boundary": next(
                (row["last_failure_boundary"] for row in rows if row["last_failure_boundary"]), ""
            ),
        }

    def close(self) -> None:
        self._connection.close()
