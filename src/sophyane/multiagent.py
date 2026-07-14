"""Durable supervisor-worker runtime for Sophyane v13.

The module creates real worker invocations with unique identities, persistent
SQLite lifecycle records, bounded retries, concurrent execution and a final
review/merge phase. It deliberately distinguishes worker instances from mere
role-labelled prompt sections.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Protocol

from sophyane.config import DATA_DIR, ensure_directories

ExecutionMode = Literal["auto", "single", "multi"]
WorkerStatus = Literal["queued", "running", "completed", "failed"]


class AgentBackend(Protocol):
    """Backend used by each independent worker invocation."""

    def __call__(self, prompt: str, system_prompt: str) -> str:
        """Return one worker response."""


@dataclass(frozen=True)
class TaskAssessment:
    score: int
    mode: Literal["single_agent", "multi_agent"]
    reasons: tuple[str, ...]
    roles: tuple[str, ...]


@dataclass(frozen=True)
class WorkerSpec:
    role: str
    objective: str
    depends_on: tuple[str, ...] = ()


@dataclass
class WorkerResult:
    worker_id: str
    role: str
    status: WorkerStatus
    attempts: int
    output: str = ""
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class MultiAgentResult:
    run_id: str
    mode: Literal["single_agent", "multi_agent"]
    supervisor_id: str
    assessment: TaskAssessment
    workers: list[WorkerResult]
    final_output: str
    started_at: float
    finished_at: float
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["assessment"]["reasons"] = list(self.assessment.reasons)
        data["assessment"]["roles"] = list(self.assessment.roles)
        return data


class MultiAgentStore:
    """SQLite store for runs, workers, events and messages."""

    def __init__(self, path: Path | None = None) -> None:
        ensure_directories()
        self.path = Path(path or (DATA_DIR / "multiagent.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    supervisor_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    assessment_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_output TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_workers (
                    worker_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    output TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    started_at REAL,
                    finished_at REAL,
                    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_workers_run
                    ON agent_workers(run_id);
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_run
                    ON agent_events(run_id, id);
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def create_run(
        self,
        run_id: str,
        supervisor_id: str,
        prompt: str,
        assessment: TaskAssessment,
    ) -> None:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_runs(
                    run_id, supervisor_id, mode, prompt, assessment_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)""",
                (
                    run_id,
                    supervisor_id,
                    assessment.mode,
                    prompt,
                    json.dumps(asdict(assessment), sort_keys=True),
                    now,
                    now,
                ),
            )
            connection.commit()

    def add_worker(self, run_id: str, worker_id: str, spec: WorkerSpec) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_workers(
                    worker_id, run_id, role, objective, status
                ) VALUES (?, ?, ?, ?, 'queued')""",
                (worker_id, run_id, spec.role, spec.objective),
            )
            connection.commit()

    def update_worker(self, result: WorkerResult) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """UPDATE agent_workers SET status=?, attempts=?, output=?,
                    error=?, started_at=?, finished_at=? WHERE worker_id=?""",
                (
                    result.status,
                    result.attempts,
                    result.output,
                    result.error,
                    result.started_at,
                    result.finished_at,
                    result.worker_id,
                ),
            )
            connection.commit()

    def event(
        self,
        run_id: str,
        actor_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_events(
                    run_id, actor_id, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (
                    run_id,
                    actor_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    time.time(),
                ),
            )
            connection.commit()

    def message(
        self,
        run_id: str,
        sender_id: str,
        recipient_id: str,
        content: str,
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_messages(
                    run_id, sender_id, recipient_id, content, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (run_id, sender_id, recipient_id, content, time.time()),
            )
            connection.commit()

    def finish_run(self, run_id: str, output: str, status: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """UPDATE agent_runs SET final_output=?, status=?, updated_at=?
                    WHERE run_id=?""",
                (output, status, time.time(), run_id),
            )
            connection.commit()

    def trace(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT actor_id, event_type, payload_json, created_at
                    FROM agent_events WHERE run_id=? ORDER BY id""",
                (run_id,),
            ).fetchall()
        return [
            {
                "actor_id": row["actor_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def inspect_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            run = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not run:
                return None
            workers = connection.execute(
                "SELECT * FROM agent_workers WHERE run_id=? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return {
            "run": dict(run),
            "workers": [dict(worker) for worker in workers],
            "trace": self.trace(run_id),
        }


class ComplexityRouter:
    """Deterministic task router with explicit escalation signals."""

    COMPLEX_MARKERS = {
        "frontend",
        "backend",
        "database",
        "authentication",
        "security",
        "docker",
        "deployment",
        "documentation",
        "integration",
        "benchmark",
        "migration",
        "rollback",
        "ci",
        "api",
    }
    SIMPLE_MARKERS = {"explain", "summarize", "one query", "syntax error", "rename"}

    def assess(self, prompt: str, mode: ExecutionMode = "auto") -> TaskAssessment:
        lowered = prompt.lower()
        if mode == "single":
            return TaskAssessment(0, "single_agent", ("forced single-agent mode",), ("executor",))
        if mode == "multi":
            return TaskAssessment(99, "multi_agent", ("forced multi-agent mode",), self.roles_for(prompt))

        score = 0
        reasons: list[str] = []
        marker_hits = sorted(marker for marker in self.COMPLEX_MARKERS if marker in lowered)
        if len(marker_hits) >= 2:
            score += min(6, len(marker_hits))
            reasons.append("multiple specialist domains: " + ", ".join(marker_hits))
        if any(token in lowered for token in ("complete", "production", "full-stack", "entire project")):
            score += 3
            reasons.append("large deliverable scope")
        if any(token in lowered for token in ("tests", "test", "review", "audit", "validate")):
            score += 2
            reasons.append("independent verification requested")
        if any(token in lowered for token in ("parallel", "multiple agents", "multi-agent")):
            score += 4
            reasons.append("parallel or multi-agent execution requested")
        if any(marker in lowered for marker in self.SIMPLE_MARKERS) and score == 0:
            reasons.append("single narrow deliverable")
        if not reasons:
            reasons.append("default low-complexity task")

        multi = score >= 5
        return TaskAssessment(
            score,
            "multi_agent" if multi else "single_agent",
            tuple(reasons),
            self.roles_for(prompt) if multi else ("executor",),
        )

    def roles_for(self, prompt: str) -> tuple[str, ...]:
        lowered = prompt.lower()
        roles: list[str] = ["planner"]
        if any(x in lowered for x in ("code", "api", "backend", "frontend", "implement", "build")):
            roles.append("coder")
        if "database" in lowered or "sqlite" in lowered or "schema" in lowered:
            roles.append("database")
        if "security" in lowered or "authentication" in lowered or "audit" in lowered:
            roles.append("security")
        if "test" in lowered or "validate" in lowered or "ci" in lowered:
            roles.append("tester")
        if "document" in lowered or "readme" in lowered:
            roles.append("documentation")
        if "deploy" in lowered or "docker" in lowered or "rollback" in lowered:
            roles.append("operations")
        roles.append("reviewer")
        return tuple(dict.fromkeys(roles))


ROLE_SYSTEM_PROMPTS = {
    "planner": "You are the planning agent. Produce requirements, architecture, risks and an ordered execution plan.",
    "coder": "You are the coding agent. Produce concrete implementation details and code-oriented deliverables.",
    "database": "You are the database agent. Design schemas, transactions, migrations and data integrity checks.",
    "security": "You are the security reviewer. Identify vulnerabilities and specify safe corrections.",
    "tester": "You are the test agent. Define and evaluate unit, integration, lint and failure-path tests.",
    "documentation": "You are the documentation agent. Produce concise usage and maintenance documentation.",
    "operations": "You are the operations agent. Cover packaging, CI, deployment, monitoring and rollback.",
    "reviewer": "You are the independent reviewer. Check correctness, conflicts, missing requirements and release readiness.",
    "executor": "You are the single execution agent. Solve the task completely and validate the answer.",
}


class MultiAgentRuntime:
    """Supervisor that launches and coordinates independent worker calls."""

    def __init__(
        self,
        backend: AgentBackend,
        store: MultiAgentStore | None = None,
        router: ComplexityRouter | None = None,
        max_workers: int = 6,
        max_attempts: int = 2,
    ) -> None:
        self.backend = backend
        self.store = store or MultiAgentStore()
        self.router = router or ComplexityRouter()
        self.max_workers = max(1, max_workers)
        self.max_attempts = max(1, max_attempts)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def _specs(self, prompt: str, assessment: TaskAssessment) -> list[WorkerSpec]:
        return [
            WorkerSpec(
                role=role,
                objective=(
                    f"User task:\n{prompt}\n\nComplete the {role} responsibility. "
                    "State assumptions, concrete output, validation and unresolved risks."
                ),
            )
            for role in assessment.roles
            if role != "reviewer"
        ]

    def _run_worker(
        self,
        run_id: str,
        supervisor_id: str,
        worker_id: str,
        spec: WorkerSpec,
        context: str = "",
    ) -> WorkerResult:
        result = WorkerResult(worker_id, spec.role, "queued", 0)
        self.store.message(run_id, supervisor_id, worker_id, spec.objective)
        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt
            result.status = "running"
            result.started_at = result.started_at or time.time()
            self.store.update_worker(result)
            self.store.event(run_id, worker_id, "worker_started", {"role": spec.role, "attempt": attempt})
            try:
                prompt = spec.objective
                if context:
                    prompt += "\n\nShared worker context:\n" + context
                output = self.backend(prompt, ROLE_SYSTEM_PROMPTS.get(spec.role, ROLE_SYSTEM_PROMPTS["executor"]))
                result.output = output
                result.error = ""
                result.status = "completed"
                result.finished_at = time.time()
                self.store.update_worker(result)
                self.store.message(run_id, worker_id, supervisor_id, output)
                self.store.event(run_id, worker_id, "worker_completed", {"attempt": attempt, "output_chars": len(output)})
                return result
            except Exception as error:  # backend errors must be captured durably
                result.error = f"{type(error).__name__}: {error}"
                self.store.event(run_id, worker_id, "worker_failed_attempt", {"attempt": attempt, "error": result.error})
                if attempt >= self.max_attempts:
                    result.status = "failed"
                    result.finished_at = time.time()
                    self.store.update_worker(result)
                    return result
        return result

    def _review_and_merge(
        self,
        run_id: str,
        supervisor_id: str,
        prompt: str,
        results: Iterable[WorkerResult],
    ) -> WorkerResult:
        worker_id = self._new_id("agent-reviewer")
        spec = WorkerSpec("reviewer", "Review and merge the worker outputs")
        self.store.add_worker(run_id, worker_id, spec)
        completed = [result for result in results if result.status == "completed"]
        context = "\n\n".join(
            f"### {result.role} ({result.worker_id})\n{result.output}" for result in completed
        )
        objective = (
            f"Original user task:\n{prompt}\n\nReview the following independent worker outputs. "
            "Resolve conflicts, reject unsupported claims, ensure requirements are covered, and return one final actionable answer.\n\n"
            + context
        )
        return self._run_worker(
            run_id,
            supervisor_id,
            worker_id,
            WorkerSpec("reviewer", objective),
        )

    def run(self, prompt: str, mode: ExecutionMode = "auto") -> MultiAgentResult:
        started = time.time()
        assessment = self.router.assess(prompt, mode)
        run_id = self._new_id("run")
        supervisor_id = self._new_id("supervisor")
        self.store.create_run(run_id, supervisor_id, prompt, assessment)
        self.store.event(run_id, supervisor_id, "route_decided", asdict(assessment))

        if assessment.mode == "single_agent":
            spec = WorkerSpec("executor", prompt)
            worker_id = self._new_id("agent-executor")
            self.store.add_worker(run_id, worker_id, spec)
            worker = self._run_worker(run_id, supervisor_id, worker_id, spec)
            final_output = worker.output if worker.status == "completed" else worker.error
            status = "completed" if worker.status == "completed" else "failed"
            self.store.finish_run(run_id, final_output, status)
            return MultiAgentResult(
                run_id,
                assessment.mode,
                supervisor_id,
                assessment,
                [worker],
                final_output,
                started,
                time.time(),
                self.store.trace(run_id),
            )

        specs = self._specs(prompt, assessment)
        assignments: list[tuple[str, WorkerSpec]] = []
        for spec in specs:
            worker_id = self._new_id(f"agent-{spec.role}")
            self.store.add_worker(run_id, worker_id, spec)
            assignments.append((worker_id, spec))
        self.store.event(run_id, supervisor_id, "workers_launched", {"count": len(assignments), "worker_ids": [item[0] for item in assignments]})

        results: list[WorkerResult] = []
        with futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(assignments))) as executor:
            pending = {
                executor.submit(self._run_worker, run_id, supervisor_id, worker_id, spec): worker_id
                for worker_id, spec in assignments
            }
            for future in futures.as_completed(pending):
                results.append(future.result())

        reviewer = self._review_and_merge(run_id, supervisor_id, prompt, results)
        results.append(reviewer)
        final_output = reviewer.output if reviewer.status == "completed" else "\n\n".join(
            result.output for result in results if result.status == "completed"
        )
        failed = [result for result in results if result.status == "failed"]
        status = "completed_with_failures" if failed and final_output else "failed" if not final_output else "completed"
        self.store.finish_run(run_id, final_output, status)
        self.store.event(run_id, supervisor_id, "run_completed", {"status": status, "failed_workers": [result.worker_id for result in failed]})
        return MultiAgentResult(
            run_id,
            assessment.mode,
            supervisor_id,
            assessment,
            results,
            final_output,
            started,
            time.time(),
            self.store.trace(run_id),
        )
