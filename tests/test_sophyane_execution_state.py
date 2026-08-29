from pathlib import Path

from sophyane.environment.execution_state import (
    MAX_RECENT_EVENTS,
    ExecutionState,
    create_execution_state,
)


def test_skill_specification_is_immutable_context():
    state = create_execution_state(
        skill_id="demo",
        objective="complete the scenario",
        constraints=(
            "do not delete data",
        ),
        success_criteria=(
            "done is true",
        ),
    )

    original = (
        state.skill.fingerprint
    )

    state.merge_state(
        {
            "done": False,
        },
        reason="initial",
    )

    state.merge_state(
        {
            "done": True,
        },
        reason="completion",
    )

    assert (
        state.skill.fingerprint
        == original
    )


def test_current_state_replaces_historical_reconstruction():
    state = create_execution_state(
        skill_id="state",
        objective="track current value",
        initial_state={
            "value": 1,
        },
    )

    state.replace_state(
        {
            "value": 2,
        },
        reason="update",
    )

    state.replace_state(
        {
            "value": 3,
        },
        reason="update",
    )

    context = (
        state.model_context()
    )

    assert (
        context[
            "current_state"
        ][
            "value"
        ]
        == 3
    )

    rendered = (
        state.model_context_json()
    )

    assert (
        '"value":3'
        in rendered
    )


def test_intermediate_reasoning_is_not_model_context():
    state = create_execution_state(
        skill_id="clean",
        objective="finish",
    )

    state.observe(
        source="worker",
        kind="observation",
        payload={
            "result":
                "current fact",
        },
    )

    rendered = (
        state.model_context_json()
    ).casefold()

    assert (
        "chain_of_thought"
        not in rendered
    )

    assert (
        "reasoning transcript"
        not in rendered
    )


def test_recent_events_are_bounded():
    state = create_execution_state(
        skill_id="bounded",
        objective="observe many events",
    )

    for index in range(
        MAX_RECENT_EVENTS
        + 20
    ):
        state.observe(
            source="environment",
            kind="tick",
            payload={
                "index":
                    index,
            },
        )

    assert (
        len(
            state.recent_events
        )
        == MAX_RECENT_EVENTS
    )


def test_checkpoint_restore_round_trip(
    tmp_path: Path,
):
    state = create_execution_state(
        skill_id="checkpoint",
        objective="resume",
        initial_state={
            "step": 1,
        },
    )

    state.observe(
        source="environment",
        kind="message",
        payload={
            "message":
                "hello"
        },
    )

    state.merge_state(
        {
            "step": 2,
        },
        reason="progress",
    )

    path = state.checkpoint(
        tmp_path
        / "state.json"
    )

    restored = (
        ExecutionState.restore(
            path
        )
    )

    assert (
        restored.skill.fingerprint
        == state.skill.fingerprint
    )

    assert (
        restored.state
        == state.state
    )

    assert (
        restored.state_digest
        == state.state_digest
    )

    assert (
        restored.latest_observation
        == state.latest_observation
    )


def test_duplicate_state_does_not_change_digest():
    state = create_execution_state(
        skill_id="stable",
        objective="stable state",
        initial_state={
            "ready": True,
        },
    )

    before = (
        state.state_digest
    )

    state.replace_state(
        {
            "ready": True,
        },
        reason="same",
    )

    assert (
        state.state_digest
        == before
    )
