"""Collaborative Orchestration Interface (COI).

COI is Sophyane's dependency-free internal protocol for coordinating agents,
tasks, artifacts, permissions, evaluation and traces. MCP remains the external
tool interoperability layer.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

COI_ROOT = Path.home() / ".sophyane" / "coi"


def ensure_coi_filesystem(root: Path = COI_ROOT) -> dict[str, str]:
    names = ("agents", "tasks", "runs", "events", "artifacts", "queues", "knowledge", "contracts", "permissions", "metrics")
    root.mkdir(parents=True, exist_ok=True)
    result = {"root": str(root)}
    for name in names:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        result[name] = str(path)
    return result


@dataclass(slots=True)
class AgentManifest:
    name: str
    role: str
    skills: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    provider: str = "dispatcher"
    max_steps: int = 8
    version: str = "1"


@dataclass(slots=True)
class TaskContract:
    goal: str
    owner: str = "supervisor"
    priority: int = 50
    parent: str = ""
    workspace: str = ""
    repository: str = ""
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class COIEvent:
    task_id: str
    kind: str
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class COIOrchestrator:
    """Bounded supervisor for native Sophyane sub-agents.

    Agent runners receive a TaskContract and shared context, and return a JSON-
    serializable result. The orchestrator records every transition locally.
    """

    def __init__(self, root: Path = COI_ROOT) -> None:
        self.paths = ensure_coi_filesystem(root)
        self.agents: dict[str, tuple[AgentManifest, Callable[[TaskContract, dict[str, Any]], dict[str, Any]]]] = {}

    def register(self, manifest: AgentManifest, runner: Callable[[TaskContract, dict[str, Any]], dict[str, Any]]) -> None:
        self.agents[manifest.name] = (manifest, runner)
        path = Path(self.paths["agents"]) / f"{manifest.name}.json"
        path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")

    def emit(self, event: COIEvent) -> None:
        path = Path(self.paths["events"]) / f"{event.task_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def submit(self, task: TaskContract) -> Path:
        path = Path(self.paths["tasks"]) / f"{task.task_id}.json"
        path.write_text(json.dumps(asdict(task), indent=2) + "\n", encoding="utf-8")
        self.emit(COIEvent(task.task_id, "task.submitted", task.owner, {"goal": task.goal}))
        return path

    def run(self, task: TaskContract, *, agent: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.submit(task)
        if agent not in self.agents:
            result = {"ok": False, "error": f"unknown COI agent: {agent}", "available": sorted(self.agents)}
            self.emit(COIEvent(task.task_id, "task.failed", "orchestrator", result))
            return result
        manifest, runner = self.agents[agent]
        missing = sorted(set(task.permissions) - set(manifest.permissions))
        if missing:
            result = {"ok": False, "error": "permission denied", "missing": missing, "agent": agent}
            self.emit(COIEvent(task.task_id, "task.denied", agent, result))
            return result
        started = time.monotonic()
        self.emit(COIEvent(task.task_id, "agent.started", agent, {"role": manifest.role}))
        try:
            output = runner(task, context or {})
            result = {"ok": True, "task_id": task.task_id, "agent": agent, "elapsed_seconds": round(time.monotonic() - started, 6), "output": output}
            self.emit(COIEvent(task.task_id, "agent.completed", agent, result))
        except Exception as error:  # noqa: BLE001
            result = {"ok": False, "task_id": task.task_id, "agent": agent, "error": f"{type(error).__name__}: {error}"}
            self.emit(COIEvent(task.task_id, "agent.failed", agent, result))
        run_path = Path(self.paths["runs"]) / f"{task.task_id}.json"
        run_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return result


def status() -> dict[str, Any]:
    paths = ensure_coi_filesystem()
    return {"ok": True, "protocol": "sophyane-coi/1", "paths": paths}
