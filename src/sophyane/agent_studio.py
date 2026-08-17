from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import time
import uuid
from typing import Any, Protocol

from sophyane.state_graph import (
    END,
    MemorySaver,
    StateGraph,
)


class AgentStudioError(RuntimeError):
    pass


VALID_STATUSES = {
    "created",
    "running",
    "waiting",
    "approval_required",
    "completed",
    "failed",
    "stopped",
    "budget_exhausted",
}


@dataclass(frozen=True)
class AgentLoop:
    interval_seconds: int | None = None
    max_steps_per_run: int = 32
    retry_limit: int = 3

    def __post_init__(self) -> None:
        if self.max_steps_per_run <= 0:
            raise AgentStudioError(
                "max_steps_per_run must be positive"
            )
        if self.retry_limit < 0:
            raise AgentStudioError(
                "retry_limit cannot be negative"
            )
        if (
            self.interval_seconds is not None
            and self.interval_seconds < 0
        ):
            raise AgentStudioError(
                "interval_seconds cannot be negative"
            )


@dataclass(frozen=True)
class AgentBudget:
    max_daily_cost: float | None = None
    max_monthly_cost: float | None = None
    max_run_cost: float | None = None
    max_run_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.max_daily_cost,
            self.max_monthly_cost,
            self.max_run_cost,
        ):
            if value is not None and value < 0:
                raise AgentStudioError(
                    "cost budgets cannot be negative"
                )

        if (
            self.max_run_tokens is not None
            and self.max_run_tokens < 0
        ):
            raise AgentStudioError(
                "token budget cannot be negative"
            )


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    goal: str
    template: str
    tools: tuple[str, ...]
    model_policy: str = "balanced"
    memory_enabled: bool = True
    allowed_domains: tuple[str, ...] = ()
    approval_required_for: tuple[str, ...] = (
        "destructive",
        "financial",
        "deployment",
        "publication",
        "account_change",
    )
    stop_when: tuple[str, ...] = (
        "goal_complete",
        "user_stop",
        "budget_exhausted",
    )
    loop: AgentLoop = field(
        default_factory=AgentLoop
    )
    budget: AgentBudget = field(
        default_factory=AgentBudget
    )

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise AgentStudioError(
                "agent_id is required"
            )
        if not self.name.strip():
            raise AgentStudioError(
                "name is required"
            )
        if not self.goal.strip():
            raise AgentStudioError(
                "goal is required"
            )
        if self.model_policy not in {
            "best",
            "balanced",
            "free_first",
            "local_first",
            "lowest_cost",
        }:
            raise AgentStudioError(
                "unsupported model_policy"
            )

    def stable_hash(self) -> str:
        payload = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(
            payload.encode("utf-8")
        ).hexdigest()


@dataclass
class RunState:
    agent_id: str
    run_id: str
    graph_version: str
    status: str = "created"
    current_node: str | None = None
    step_count: int = 0
    accumulated_cost: float = 0.0
    accumulated_tokens: int = 0
    retries: int = 0
    next_wake_at: float | None = None
    approval_id: str | None = None
    approval_granted: bool = False
    goal_complete: bool = False
    stop_requested: bool = False
    last_output: str | None = None
    events: list[dict[str, Any]] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise AgentStudioError(
                f"invalid run status: {self.status}"
            )


class CheckpointStore(Protocol):
    def put(
        self,
        run_id: str,
        state: dict[str, Any],
    ) -> None:
        ...

    def get(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        ...


class ModelExecutor(Protocol):
    def execute(
        self,
        *,
        goal: str,
        node: str,
        state: dict[str, Any],
        model_policy: str,
    ) -> dict[str, Any]:
        ...


class ToolExecutor(Protocol):
    def execute(
        self,
        *,
        tool: str,
        goal: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class ApprovalStore(Protocol):
    def is_approved(
        self,
        approval_id: str,
    ) -> bool:
        ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._approved: set[str] = set()

    def approve(
        self,
        approval_id: str,
    ) -> None:
        self._approved.add(
            approval_id
        )

    def is_approved(
        self,
        approval_id: str,
    ) -> bool:
        return (
            approval_id
            in self._approved
        )


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._data: dict[
            str,
            dict[str, Any],
        ] = {}

    def put(
        self,
        run_id: str,
        state: dict[str, Any],
    ) -> None:
        self._data[run_id] = (
            json.loads(
                json.dumps(state)
            )
        )

    def get(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        row = self._data.get(
            run_id
        )
        if row is None:
            return None
        return json.loads(
            json.dumps(row)
        )


class MockModelExecutor:
    def execute(
        self,
        *,
        goal: str,
        node: str,
        state: dict[str, Any],
        model_policy: str,
    ) -> dict[str, Any]:
        return {
            "text": (
                f"{node} completed for {goal}"
            ),
            "cost": 0.0,
            "tokens": 1,
            "goal_complete": (
                node == "verify"
                and state.get(
                    "verified",
                    False,
                )
            ),
        }


class MockToolExecutor:
    def execute(
        self,
        *,
        tool: str,
        goal: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "text": (
                f"{tool} executed for {goal}"
            ),
            "cost": 0.0,
            "tokens": 0,
        }


NOVICE_TEMPLATES = {
    "research": {
        "name": "Research Agent",
        "tools": (
            "web_search",
            "browser",
            "calculator",
        ),
    },
    "monitoring": {
        "name": "Monitoring Agent",
        "tools": (
            "web_search",
            "browser",
        ),
    },
    "coding": {
        "name": "Coding Agent",
        "tools": (
            "repository",
            "tests",
        ),
    },
    "business": {
        "name": "Business Operations Agent",
        "tools": (
            "web_search",
            "calculator",
        ),
    },
    "personal": {
        "name": "Personal Workflow Agent",
        "tools": (
            "calendar",
            "email",
        ),
    },
}


def _template_for_goal(
    goal: str,
) -> str:
    text = goal.casefold()

    if any(
        token in text
        for token in (
            "code",
            "repository",
            "software",
            "bug",
            "test",
        )
    ):
        return "coding"

    if any(
        token in text
        for token in (
            "monitor",
            "watch",
            "alert",
            "track",
            "every day",
            "every hour",
        )
    ):
        return "monitoring"

    if any(
        token in text
        for token in (
            "supplier",
            "business",
            "price",
            "sales",
            "operation",
        )
    ):
        return "business"

    if any(
        token in text
        for token in (
            "calendar",
            "email",
            "personal",
            "remind",
        )
    ):
        return "personal"

    return "research"


def compile_goal(
    goal: str,
    *,
    model_policy: str = "balanced",
    max_steps_per_run: int = 32,
) -> AgentSpec:
    clean = " ".join(
        goal.strip().split()
    )

    if not clean:
        raise AgentStudioError(
            "goal is required"
        )

    template = _template_for_goal(
        clean
    )
    info = NOVICE_TEMPLATES[
        template
    ]

    digest = sha256(
        clean.encode("utf-8")
    ).hexdigest()[:12]

    return AgentSpec(
        agent_id=f"agent-{digest}",
        name=info["name"],
        goal=clean,
        template=template,
        tools=tuple(
            info["tools"]
        ),
        model_policy=model_policy,
        loop=AgentLoop(
            max_steps_per_run=(
                max_steps_per_run
            )
        ),
    )


class AgentRuntime:
    GRAPH_VERSION = "agent-studio-v1"

    def __init__(
        self,
        *,
        model_executor: ModelExecutor,
        tool_executor: ToolExecutor,
        checkpoint_store: CheckpointStore | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        self.model_executor = (
            model_executor
        )
        self.tool_executor = (
            tool_executor
        )
        self.checkpoints = (
            checkpoint_store
            or InMemoryCheckpointStore()
        )
        self.approvals = (
            approval_store
            or InMemoryApprovalStore()
        )

    def _event(
        self,
        state: dict[str, Any],
        *,
        node: str,
        status: str,
        detail: str,
    ) -> dict[str, Any]:
        sequence = len(
            state.get(
                "events",
                [],
            )
        )

        return {
            "sequence": sequence,
            "node": node,
            "status": status,
            "detail": detail,
        }

    def _budget_exhausted(
        self,
        spec: AgentSpec,
        state: dict[str, Any],
    ) -> bool:
        run_cost = float(
            state.get(
                "accumulated_cost",
                0.0,
            )
        )

        tokens = int(
            state.get(
                "accumulated_tokens",
                0,
            )
        )

        if (
            spec.budget.max_run_cost
            is not None
            and run_cost
            >= spec.budget.max_run_cost
        ):
            return True

        if (
            spec.budget.max_run_tokens
            is not None
            and tokens
            >= spec.budget.max_run_tokens
        ):
            return True

        return False

    def _apply_model(
        self,
        spec: AgentSpec,
        state: dict[str, Any],
        node: str,
    ) -> dict[str, Any]:
        result = (
            self.model_executor.execute(
                goal=spec.goal,
                node=node,
                state=dict(state),
                model_policy=(
                    spec.model_policy
                ),
            )
        )

        state["last_output"] = str(
            result.get(
                "text",
                "",
            )
        )

        state["accumulated_cost"] = (
            float(
                state.get(
                    "accumulated_cost",
                    0.0,
                )
            )
            + float(
                result.get(
                    "cost",
                    0.0,
                )
            )
        )

        state["accumulated_tokens"] = (
            int(
                state.get(
                    "accumulated_tokens",
                    0,
                )
            )
            + int(
                result.get(
                    "tokens",
                    0,
                )
            )
        )

        if bool(
            result.get(
                "goal_complete",
                False,
            )
        ):
            state[
                "goal_complete"
            ] = True

        return state

    def _graph(
        self,
        spec: AgentSpec,
    ):
        graph = StateGraph()

        def node(
            name: str,
        ):
            def run(
                state: dict[str, Any],
            ) -> dict[str, Any]:
                working = dict(state)

                working[
                    "current_node"
                ] = name
                working["status"] = (
                    "running"
                )
                working["step_count"] = (
                    int(
                        state.get(
                            "step_count",
                            0,
                        )
                    )
                    + 1
                )

                if (
                    working["step_count"]
                    > spec.loop.max_steps_per_run
                ):
                    event = self._event(
                        state,
                        node=name,
                        status="stopped",
                        detail=(
                            "step limit reached"
                        ),
                    )

                    return {
                        "current_node": name,
                        "status": "stopped",
                        "step_count": (
                            working[
                                "step_count"
                            ]
                        ),
                        "stop_reason": (
                            "step_limit"
                        ),
                        "events": [event],
                    }

                before_cost = float(
                    state.get(
                        "accumulated_cost",
                        0.0,
                    )
                )
                before_tokens = int(
                    state.get(
                        "accumulated_tokens",
                        0,
                    )
                )

                self._apply_model(
                    spec,
                    working,
                    name,
                )

                status = (
                    "running"
                )
                stop_reason = None

                if self._budget_exhausted(
                    spec,
                    working,
                ):
                    status = (
                        "budget_exhausted"
                    )
                    stop_reason = (
                        "budget_exhausted"
                    )

                event = self._event(
                    state,
                    node=name,
                    status=status,
                    detail=(
                        f"{name} completed"
                    ),
                )

                update = {
                    "current_node": name,
                    "status": status,
                    "step_count": (
                        working[
                            "step_count"
                        ]
                    ),
                    "accumulated_cost": (
                        float(
                            working.get(
                                "accumulated_cost",
                                before_cost,
                            )
                        )
                    ),
                    "accumulated_tokens": (
                        int(
                            working.get(
                                "accumulated_tokens",
                                before_tokens,
                            )
                        )
                    ),
                    "last_output": (
                        working.get(
                            "last_output"
                        )
                    ),
                    "goal_complete": (
                        bool(
                            working.get(
                                "goal_complete",
                                state.get(
                                    "goal_complete",
                                    False,
                                ),
                            )
                        )
                    ),
                    "events": [event],
                }

                if stop_reason:
                    update[
                        "stop_reason"
                    ] = stop_reason

                return update

            return run

        for name in (
            "understand_goal",
            "load_memory",
            "plan",
            "act",
            "analyze",
            "verify",
            "store_memory",
            "goal_check",
            "approval",
            "wait",
        ):
            graph.add_node(
                name,
                node(name),
            )

        graph.set_entry_point(
            "understand_goal"
        )

        graph.add_edge(
            "understand_goal",
            "load_memory",
        )
        graph.add_edge(
            "load_memory",
            "plan",
        )
        graph.add_edge(
            "plan",
            "act",
        )
        graph.add_edge(
            "act",
            "analyze",
        )
        graph.add_edge(
            "analyze",
            "verify",
        )
        graph.add_edge(
            "verify",
            "store_memory",
        )
        graph.add_edge(
            "store_memory",
            "goal_check",
        )

        def goal_route(
            state: dict[str, Any],
        ) -> str:
            if state.get(
                "status"
            ) in {
                "budget_exhausted",
                "stopped",
                "failed",
            }:
                return "end"

            if state.get(
                "goal_complete",
                False,
            ):
                return "end"

            if state.get(
                "requires_approval",
                False,
            ):
                return "approval"

            if (
                spec.loop.interval_seconds
                is not None
            ):
                return "wait"

            return "replan"

        graph.add_conditional_edges(
            "goal_check",
            goal_route,
            {
                "end": END,
                "approval": "approval",
                "wait": "wait",
                "replan": "plan",
            },
        )

        def approval_route(
            state: dict[str, Any],
        ) -> str:
            approval_id = (
                state.get(
                    "approval_id"
                )
            )

            if (
                approval_id
                and self.approvals.is_approved(
                    str(
                        approval_id
                    )
                )
            ):
                state[
                    "approval_granted"
                ] = True
                state[
                    "requires_approval"
                ] = False
                return "resume"

            state["status"] = (
                "approval_required"
            )
            return "end"

        graph.add_conditional_edges(
            "approval",
            approval_route,
            {
                "resume": "act",
                "end": END,
            },
        )

        def wait_route(
            state: dict[str, Any],
        ) -> str:
            state["status"] = (
                "waiting"
            )

            interval = (
                spec.loop.interval_seconds
                or 0
            )

            state[
                "next_wake_at"
            ] = (
                time.time()
                + interval
            )

            return "end"

        graph.add_conditional_edges(
            "wait",
            wait_route,
            {
                "end": END,
            },
        )

        return graph.compile(
            checkpointer=MemorySaver()
        )

    def run(
        self,
        spec: AgentSpec,
        *,
        run_id: str | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = (
            run_id
            or f"run-{uuid.uuid4()}"
        )

        state = {
            "agent_id": spec.agent_id,
            "run_id": run_id,
            "graph_version": (
                self.GRAPH_VERSION
            ),
            "status": "created",
            "current_node": None,
            "step_count": 0,
            "accumulated_cost": 0.0,
            "accumulated_tokens": 0,
            "goal_complete": False,
            "stop_requested": False,
            "events": [],
            **(
                initial_state
                or {}
            ),
        }

        graph = self._graph(
            spec
        )

        result = graph.invoke(
            state,
            config={
                "configurable": {
                    "thread_id": run_id
                }
            },
            max_steps=(
                spec.loop.max_steps_per_run
            ),
        )

        if result.get(
            "goal_complete"
        ):
            result["status"] = (
                "completed"
            )

        self.checkpoints.put(
            run_id,
            result,
        )

        return result

    def resume(
        self,
        spec: AgentSpec,
        run_id: str,
    ) -> dict[str, Any]:
        state = self.checkpoints.get(
            run_id
        )

        if state is None:
            raise AgentStudioError(
                "checkpoint not found"
            )

        if (
            state.get(
                "status"
            )
            == "waiting"
        ):
            wake = state.get(
                "next_wake_at"
            )

            if (
                wake is not None
                and time.time()
                < float(wake)
            ):
                return state

        return self.run(
            spec,
            run_id=run_id,
            initial_state=state,
        )


__all__ = [
    "AgentBudget",
    "AgentLoop",
    "AgentRuntime",
    "AgentSpec",
    "AgentStudioError",
    "InMemoryApprovalStore",
    "InMemoryCheckpointStore",
    "MockModelExecutor",
    "MockToolExecutor",
    "NOVICE_TEMPLATES",
    "RunState",
    "compile_goal",
]
