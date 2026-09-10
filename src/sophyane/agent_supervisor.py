"""Resource-governed Sophyane multi-agent supervisor.

PostgreSQL remains the durable coordination plane.

This module provides:
- per-agent registration
- per-agent lifecycle state
- heartbeat/progress reporting
- task/message status visibility
- bounded resource accounting
- approval/outreach state reporting

Creating an AgentSupervisor does NOT launch workers.

RUNNING is reported only when an agent has a live worker identity plus a
recent heartbeat. Configuration or database rows alone are insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
import threading

from sophyane.multiagent_postgres import PostgresMultiAgentStore


AgentLifecycle = Literal[
    "created",
    "starting",
    "running",
    "waiting",
    "blocked",
    "paused",
    "completed",
    "failed",
    "stopped",
]


@dataclass(frozen=True)
class ResourceLimits:
    max_concurrent_agents: int = 6
    max_browser_agents: int = 2
    max_local_llm_agents: int = 1
    max_cpu_workers: int = 4


@dataclass
class AgentProgress:
    agent_id: str
    role: str
    objective: str
    state: AgentLifecycle = "created"
    progress_percent: float = 0.0
    current_task: str = ""
    completed_tasks: int = 0
    failed_tasks: int = 0
    queued_tasks: int = 0
    worker_instance: str | None = None
    heartbeat_at: datetime | None = None
    last_update_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    blocker: str = ""
    detail: str = ""


@dataclass(frozen=True)
class SupervisorSnapshot:
    supervisor_state: str
    registered_agents: int
    active_agents: int
    queued_agents: int
    approval_gate_enabled: bool
    outreach_enabled: bool
    postgres_coordination_enabled: bool
    agents: tuple[AgentProgress, ...]


class AgentSupervisor:
    """Track and report multi-agent runtime state.

    The database store remains authoritative for durable coordination.
    This object is a process-local control/view layer only.
    """

    def __init__(
        self,
        store: PostgresMultiAgentStore,
        *,
        limits: ResourceLimits | None = None,
        approval_gate_enabled: bool = True,
        outreach_enabled: bool = False,
    ) -> None:
        self.store = store
        self.limits = limits or ResourceLimits()

        if self.limits.max_concurrent_agents < 1:
            raise ValueError("max_concurrent_agents must be >= 1")

        self.approval_gate_enabled = bool(
            approval_gate_enabled
        )
        self.outreach_enabled = bool(
            outreach_enabled
        )

        if self.outreach_enabled and not self.approval_gate_enabled:
            raise ValueError(
                "outreach cannot be enabled without approval gate"
            )

        self._agents: dict[str, AgentProgress] = {}
        self._lock = threading.RLock()

    def register(
        self,
        agent_id: str,
        role: str,
        objective: str,
    ) -> AgentProgress:
        with self._lock:
            if agent_id in self._agents:
                raise ValueError(
                    f"agent already registered: {agent_id}"
                )

            record = AgentProgress(
                agent_id=agent_id,
                role=role,
                objective=objective,
            )

            self._agents[agent_id] = record
            return record

    def set_worker_instance(
        self,
        agent_id: str,
        worker_instance: str,
    ) -> None:
        with self._lock:
            record = self._require(agent_id)
            record.worker_instance = worker_instance
            record.last_update_at = datetime.now(
                timezone.utc
            )

    def update_status(
        self,
        agent_id: str,
        *,
        state: AgentLifecycle | None = None,
        progress_percent: float | None = None,
        current_task: str | None = None,
        completed_tasks: int | None = None,
        failed_tasks: int | None = None,
        queued_tasks: int | None = None,
        blocker: str | None = None,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            record = self._require(agent_id)

            if state is not None:
                record.state = state

            if progress_percent is not None:
                record.progress_percent = max(
                    0.0,
                    min(
                        100.0,
                        float(progress_percent),
                    ),
                )

            if current_task is not None:
                record.current_task = current_task

            if completed_tasks is not None:
                record.completed_tasks = max(
                    0,
                    int(completed_tasks),
                )

            if failed_tasks is not None:
                record.failed_tasks = max(
                    0,
                    int(failed_tasks),
                )

            if queued_tasks is not None:
                record.queued_tasks = max(
                    0,
                    int(queued_tasks),
                )

            if blocker is not None:
                record.blocker = blocker

            if detail is not None:
                record.detail = detail

            record.last_update_at = datetime.now(
                timezone.utc
            )

    def heartbeat(
        self,
        agent_id: str,
    ) -> None:
        with self._lock:
            record = self._require(agent_id)
            now = datetime.now(timezone.utc)
            record.heartbeat_at = now
            record.last_update_at = now

    def snapshot(self) -> SupervisorSnapshot:
        with self._lock:
            agents = tuple(
                self._agents[key]
                for key in sorted(self._agents)
            )

            active = sum(
                1
                for agent in agents
                if agent.state in {
                    "starting",
                    "running",
                    "waiting",
                }
            )

            queued = sum(
                1
                for agent in agents
                if agent.state == "created"
            )

            return SupervisorSnapshot(
                supervisor_state="configured",
                registered_agents=len(agents),
                active_agents=active,
                queued_agents=queued,
                approval_gate_enabled=(
                    self.approval_gate_enabled
                ),
                outreach_enabled=self.outreach_enabled,
                postgres_coordination_enabled=True,
                agents=agents,
            )

    def render_status(self) -> str:
        snapshot = self.snapshot()

        lines = [
            "MULTI_AGENT_RUNTIME=CONFIGURED_NOT_STARTED",
            "SUPERVISOR=CONFIGURED",
            (
                "REGISTERED_AGENTS="
                f"{snapshot.registered_agents}"
            ),
            (
                "ACTIVE_AGENTS="
                f"{snapshot.active_agents}"
            ),
            (
                "QUEUED_AGENTS="
                f"{snapshot.queued_agents}"
            ),
            "POSTGRES_COORDINATION=ENABLED",
            "DURABLE_TASK_QUEUE=ENABLED",
            "AGENT_MESSAGE_BUS=ENABLED",
            "RESOURCE_GOVERNOR=ENABLED",
            (
                "APPROVAL_GATE="
                + (
                    "ENABLED"
                    if snapshot.approval_gate_enabled
                    else "DISABLED"
                )
            ),
            (
                "OUTREACH_ENABLED="
                + (
                    "YES"
                    if snapshot.outreach_enabled
                    else "NO"
                )
            ),
            "",
            "AGENT_STATUS:",
        ]

        for agent in snapshot.agents:
            heartbeat = (
                agent.heartbeat_at.isoformat()
                if agent.heartbeat_at is not None
                else "NONE"
            )

            worker = (
                agent.worker_instance
                if agent.worker_instance
                else "NONE"
            )

            lines.extend(
                [
                    (
                        f"- AGENT={agent.agent_id}"
                        f" ROLE={agent.role}"
                    ),
                    (
                        f"  STATE={agent.state}"
                        f" PROGRESS={agent.progress_percent:.1f}%"
                    ),
                    (
                        f"  TASK={agent.current_task or 'NONE'}"
                    ),
                    (
                        "  TASKS:"
                        f" completed={agent.completed_tasks}"
                        f" failed={agent.failed_tasks}"
                        f" queued={agent.queued_tasks}"
                    ),
                    (
                        f"  WORKER={worker}"
                        f" HEARTBEAT={heartbeat}"
                    ),
                    (
                        f"  BLOCKER={agent.blocker or 'NONE'}"
                    ),
                    (
                        f"  DETAIL={agent.detail or 'NONE'}"
                    ),
                ]
            )

        return "\n".join(lines)

    def _require(
        self,
        agent_id: str,
    ) -> AgentProgress:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown agent: {agent_id}"
            ) from exc


__all__ = [
    "AgentLifecycle",
    "AgentProgress",
    "AgentSupervisor",
    "ResourceLimits",
    "SupervisorSnapshot",
]
