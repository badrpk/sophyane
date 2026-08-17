from __future__ import annotations

import time

from sophyane.agent_studio import (
    AgentBudget,
    AgentLoop,
    AgentRuntime,
    AgentSpec,
    InMemoryApprovalStore,
    InMemoryCheckpointStore,
    MockModelExecutor,
    MockToolExecutor,
    compile_goal,
)


def runtime(
    *,
    approvals=None,
    checkpoints=None,
):
    return AgentRuntime(
        model_executor=(
            MockModelExecutor()
        ),
        tool_executor=(
            MockToolExecutor()
        ),
        checkpoint_store=(
            checkpoints
            or InMemoryCheckpointStore()
        ),
        approval_store=(
            approvals
            or InMemoryApprovalStore()
        ),
    )


def test_plain_english_goal_compiles_deterministically():
    goal = (
        "Monitor steel scrap prices "
        "and alert me when prices fall"
    )

    a = compile_goal(goal)
    b = compile_goal(goal)

    assert a == b
    assert a.template == "monitoring"
    assert a.agent_id == b.agent_id
    assert len(a.stable_hash()) == 64


def test_coding_goal_chooses_coding_template():
    spec = compile_goal(
        "Fix the repository bug and run tests"
    )

    assert spec.template == "coding"
    assert "repository" in spec.tools


def test_default_model_policy_is_provider_independent():
    spec = compile_goal(
        "Research battery prices"
    )

    assert spec.model_policy == "balanced"

    rendered = str(spec)

    assert "GEMINI_API_KEY" not in rendered
    assert "OPENAI_API_KEY" not in rendered


def test_bounded_loop_stops_at_step_limit():
    spec = AgentSpec(
        agent_id="agent-loop",
        name="Loop",
        goal="Repeat analysis",
        template="research",
        tools=("web_search",),
        loop=AgentLoop(
            max_steps_per_run=5
        ),
    )

    result = runtime().run(spec)

    assert result["step_count"] <= 5


def test_checkpoint_can_be_reconstructed():
    checkpoints = (
        InMemoryCheckpointStore()
    )

    spec = compile_goal(
        "Research lithium prices",
        max_steps_per_run=8,
    )

    rt = runtime(
        checkpoints=checkpoints
    )

    result = rt.run(spec)

    restored = checkpoints.get(
        result["run_id"]
    )

    assert restored is not None
    assert (
        restored["run_id"]
        == result["run_id"]
    )
    assert (
        restored["events"]
        == result["events"]
    )


def test_wait_state_is_durable_without_busy_loop():
    spec = AgentSpec(
        agent_id="agent-wait",
        name="Monitor",
        goal="Monitor price",
        template="monitoring",
        tools=("web_search",),
        loop=AgentLoop(
            interval_seconds=3600,
            max_steps_per_run=16,
        ),
    )

    result = runtime().run(spec)

    assert result["status"] == "waiting"
    assert result["next_wake_at"] > time.time()


def test_wait_resume_before_due_does_not_execute():
    checkpoints = (
        InMemoryCheckpointStore()
    )

    spec = AgentSpec(
        agent_id="agent-wait-resume",
        name="Monitor",
        goal="Monitor price",
        template="monitoring",
        tools=("web_search",),
        loop=AgentLoop(
            interval_seconds=3600,
            max_steps_per_run=16,
        ),
    )

    rt = runtime(
        checkpoints=checkpoints
    )

    first = rt.run(spec)

    resumed = rt.resume(
        spec,
        first["run_id"],
    )

    assert (
        resumed["step_count"]
        == first["step_count"]
    )
    assert resumed["status"] == "waiting"


def test_human_approval_blocks_run():
    approvals = (
        InMemoryApprovalStore()
    )

    spec = compile_goal(
        "Research supplier options",
        max_steps_per_run=16,
    )

    result = runtime(
        approvals=approvals
    ).run(
        spec,
        initial_state={
            "requires_approval": True,
            "approval_id": "approval-1",
        },
    )

    assert (
        result["status"]
        == "approval_required"
    )


def test_approval_store_can_release_gate():
    approvals = (
        InMemoryApprovalStore()
    )

    approvals.approve(
        "approval-1"
    )

    assert approvals.is_approved(
        "approval-1"
    )


def test_run_budget_exhaustion():
    class PaidModel:
        def execute(
            self,
            *,
            goal,
            node,
            state,
            model_policy,
        ):
            return {
                "text": "ok",
                "cost": 1.0,
                "tokens": 10,
            }

    spec = AgentSpec(
        agent_id="agent-budget",
        name="Budget",
        goal="Research",
        template="research",
        tools=("web_search",),
        loop=AgentLoop(
            max_steps_per_run=16
        ),
        budget=AgentBudget(
            max_run_cost=1.0
        ),
    )

    rt = AgentRuntime(
        model_executor=PaidModel(),
        tool_executor=(
            MockToolExecutor()
        ),
    )

    result = rt.run(spec)

    assert (
        result["status"]
        == "budget_exhausted"
    )


def test_events_are_reproducible_shape():
    spec = compile_goal(
        "Research market prices",
        max_steps_per_run=8,
    )

    result = runtime().run(spec)

    assert result["events"]

    for index, event in enumerate(
        result["events"]
    ):
        assert (
            event["sequence"]
            == index
        )
        assert "node" in event
        assert "status" in event
        assert "detail" in event


def test_no_upstream_credentials_in_checkpoint():
    checkpoints = (
        InMemoryCheckpointStore()
    )

    spec = compile_goal(
        "Research current steel prices",
        max_steps_per_run=8,
    )

    rt = runtime(
        checkpoints=checkpoints
    )

    result = rt.run(spec)

    checkpoint = checkpoints.get(
        result["run_id"]
    )

    rendered = str(
        checkpoint
    )

    assert "GEMINI_API_KEY" not in rendered
    assert "OPENAI_API_KEY" not in rendered
    assert "ANTHROPIC_API_KEY" not in rendered
