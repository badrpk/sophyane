"""Persistent runtime tick used by sophyane-runtime.timer.

Processes local task queue without requiring a working cloud LLM when idle.
Uses the harness sandbox for command execution with timeouts and guardrails.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sophyane.harness import Guardrails, SandboxResult, SandboxRunner
from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
STATE_DB = STATE_DIR / "sophyane.sqlite3"
EVENTS_LOG = STATE_DIR / "events.jsonl"
PENDING_STATUSES = ("pending", "queued", "ready", "retry")


@dataclass
class DaemonTickReport:
    version: str
    status: str
    pending_before: int
    processed: int
    completed: int
    failed: int
    skipped: int
    tasks: list[dict[str, Any]]
    message: str

    def to_text(self) -> str:
        lines = [
            f"Sophyane daemon-tick v{self.version}",
            f"status={self.status}",
            f"pending_before={self.pending_before}",
            f"processed={self.processed}",
            f"completed={self.completed}",
            f"failed={self.failed}",
            f"skipped={self.skipped}",
            self.message,
        ]
        for item in self.tasks:
            lines.append(
                f"- {item.get('id')}: {item.get('status')} "
                f"exit={item.get('exit_code')} "
                f"{item.get('title', '')}"
            )
        return "\n".join(lines)


def _connect() -> sqlite3.Connection | None:
    if not STATE_DB.exists():
        return None
    connection = sqlite3.connect(STATE_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _append_event(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _pending_tasks(connection: sqlite3.Connection, limit: int = 5) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in PENDING_STATUSES)
    query = (
        f"SELECT * FROM tasks WHERE status IN ({placeholders}) "
        "ORDER BY created ASC LIMIT ?"
    )
    return list(
        connection.execute(query, (*PENDING_STATUSES, limit)).fetchall()
    )


def _workspace_for(connection: sqlite3.Connection, project_id: str | None) -> Path:
    if project_id:
        row = connection.execute(
            "SELECT workspace FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row and row["workspace"]:
            path = Path(str(row["workspace"]))
            if path.exists():
                return path
    return Path.cwd()


def _deps_satisfied(connection: sqlite3.Connection, deps_raw: str) -> bool:
    try:
        deps = json.loads(deps_raw or "[]")
    except json.JSONDecodeError:
        deps = []
    if not isinstance(deps, list) or not deps:
        return True
    for dep_id in deps:
        row = connection.execute(
            "SELECT status FROM tasks WHERE id = ?",
            (str(dep_id),),
        ).fetchone()
        if row is None or str(row["status"]) != "completed":
            return False
    return True


def _update_task(
    connection: sqlite3.Connection,
    task_id: str,
    *,
    status: str,
    attempts: int,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    latency_ms: float,
) -> None:
    connection.execute(
        """
        UPDATE tasks
        SET status = ?, attempts = ?, stdout = ?, stderr = ?,
            exit_code = ?, latency_ms = ?, updated = ?
        WHERE id = ?
        """,
        (
            status,
            attempts,
            stdout[:8000],
            stderr[:8000],
            exit_code,
            latency_ms,
            time.time(),
            task_id,
        ),
    )


def _run_command(
    command: str,
    *,
    cwd: Path,
    timeout: int,
    guardrails: Guardrails,
    sandbox: SandboxRunner,
) -> SandboxResult:
    decision = guardrails.check_text(command)
    if not decision.allowed:
        return SandboxResult(
            ok=False,
            exit_code=126,
            stdout="",
            stderr=decision.reason,
            timed_out=False,
            duration_ms=0.0,
            command=command,
        )
    return sandbox.run(command, cwd=cwd, timeout=timeout)


def run_daemon_tick(max_tasks: int = 5) -> DaemonTickReport:
    """Process up to ``max_tasks`` pending local queue items."""
    connection = _connect()
    if connection is None:
        report = DaemonTickReport(
            version=__version__,
            status="idle",
            pending_before=0,
            processed=0,
            completed=0,
            failed=0,
            skipped=0,
            tasks=[],
            message=f"No state database at {STATE_DB}; nothing to process.",
        )
        _append_event({"event": "daemon_tick", **asdict(report), "ts": time.time()})
        return report

    guardrails = Guardrails()
    sandbox = SandboxRunner()
    processed_rows: list[dict[str, Any]] = []
    completed = failed = skipped = 0

    try:
        pending = _pending_tasks(connection, limit=max_tasks)
        pending_before = len(pending)
        for row in pending:
            task_id = str(row["id"])
            title = str(row["title"] or "")
            command = str(row["command"] or "").strip()
            attempts = int(row["attempts"] or 0)
            max_attempts = int(row["max_attempts"] or 1)
            timeout = int(row["timeout"] or 60)
            verify = str(row["verify"] or "").strip()
            project_id = row["project_id"]

            if not command:
                skipped += 1
                _update_task(
                    connection,
                    task_id,
                    status="failed",
                    attempts=attempts + 1,
                    stdout="",
                    stderr="empty command",
                    exit_code=2,
                    latency_ms=0.0,
                )
                processed_rows.append(
                    {
                        "id": task_id,
                        "title": title,
                        "status": "failed",
                        "exit_code": 2,
                    }
                )
                continue

            if not _deps_satisfied(connection, str(row["deps"] or "[]")):
                skipped += 1
                processed_rows.append(
                    {
                        "id": task_id,
                        "title": title,
                        "status": "waiting_deps",
                        "exit_code": None,
                    }
                )
                continue

            cwd = _workspace_for(connection, str(project_id) if project_id else None)
            result = _run_command(
                command,
                cwd=cwd,
                timeout=max(1, timeout),
                guardrails=guardrails,
                sandbox=sandbox,
            )

            ok = result.ok
            stderr = result.stderr
            if ok and verify:
                verify_result = _run_command(
                    verify,
                    cwd=cwd,
                    timeout=max(1, min(timeout, 60)),
                    guardrails=guardrails,
                    sandbox=sandbox,
                )
                if not verify_result.ok:
                    ok = False
                    stderr = (
                        (stderr + "\n" if stderr else "")
                        + f"verify failed: {verify_result.stderr or verify_result.stdout}"
                    )

            attempts += 1
            if ok:
                status = "completed"
                completed += 1
            elif attempts >= max_attempts:
                status = "failed"
                failed += 1
            else:
                status = "retry"
                failed += 1

            _update_task(
                connection,
                task_id,
                status=status,
                attempts=attempts,
                stdout=result.stdout,
                stderr=stderr,
                exit_code=result.exit_code,
                latency_ms=result.duration_ms,
            )
            processed_rows.append(
                {
                    "id": task_id,
                    "title": title,
                    "status": status,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                }
            )

        connection.commit()
        processed = completed + failed
        if pending_before == 0:
            status = "idle"
            message = "Queue empty; tick complete."
        elif processed == 0 and skipped:
            status = "waiting"
            message = "Pending tasks blocked on dependencies or empty commands."
        elif failed and not completed:
            status = "degraded"
            message = "Processed queue with failures."
        else:
            status = "ok"
            message = "Processed local agent queue."

        report = DaemonTickReport(
            version=__version__,
            status=status,
            pending_before=pending_before,
            processed=processed,
            completed=completed,
            failed=failed,
            skipped=skipped,
            tasks=processed_rows,
            message=message,
        )
    finally:
        connection.close()

    _append_event({"event": "daemon_tick", **asdict(report), "ts": time.time()})
    return report
