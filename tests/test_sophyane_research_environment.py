from pathlib import Path

from sophyane.environment import (
    CompositeVerifier,
    ConstraintVerifier,
    EnvironmentAction,
    EnvironmentEvent,
    EnvironmentProfile,
    EnvironmentRedQueen,
    ExactVerifier,
    ResearchEnvironment,
    Scenario,
    StateVerifier,
    TemporalVerifier,
    replay_actions,
    save_trace,
    scenario_from_gaia2_record,
)
from sophyane.mode3_meta_rsi import (
    choose_txq_policy,
)


def test_environment_events_advance_independently():
    scenario = Scenario(
        scenario_id="clock",
        objective="observe",
        initial_state={
            "messages": 0,
        },
        events=(
            EnvironmentEvent(
                event_id="incoming",
                at=5.0,
                kind="message",
                payload={
                    "operation":
                        "increment",
                    "key":
                        "messages",
                    "amount":
                        1,
                },
            ),
        ),
    )

    env = ResearchEnvironment(
        scenario
    )

    assert env.state["messages"] == 0

    env.advance(
        5.0
    )

    assert env.state["messages"] == 1


def test_seeded_replay_is_stable():
    scenario = Scenario(
        scenario_id="replay",
        objective="set done",
        initial_state={
            "done": False,
        },
        seed=123,
    )

    actions = (
        EnvironmentAction(
            actor="sophyane",
            action="complete",
            payload={
                "operation":
                    "set",
                "key":
                    "done",
                "value":
                    True,
            },
        ),
    )

    first = replay_actions(
        scenario,
        actions,
    )

    second = replay_actions(
        scenario,
        actions,
    )

    assert first.state == second.state

    assert [
        item.state_digest
        for item in first.trace
    ] == [
        item.state_digest
        for item in second.trace
    ]


def test_composite_verifier():
    scenario = Scenario(
        scenario_id="verify",
        objective="finish before deadline",
        initial_state={
            "done": True,
            "safe": True,
        },
    )

    env = ResearchEnvironment(
        scenario
    )

    verifier = CompositeVerifier(
        (
            ExactVerifier(
                "done",
                True,
            ),
            StateVerifier(
                lambda state:
                    state.get(
                        "safe"
                    )
                    is True,
                "safe state",
            ),
            TemporalVerifier(
                lambda state:
                    state.get(
                        "done"
                    )
                    is True,
                deadline=10.0,
                description=(
                    "done before deadline"
                ),
            ),
        ),
        minimum_score=1.0,
    )

    result = verifier.verify(
        env
    )

    assert result.ok is True
    assert result.score == 1.0


def test_red_queen_increases_environment_difficulty():
    base = Scenario(
        scenario_id="base",
        objective="repair",
        profile=EnvironmentProfile(
            action_depth=1,
            event_rate=0.0,
        ),
    )

    mutated = (
        EnvironmentRedQueen(
            seed=7
        ).mutate(
            base,
            generation=4,
        )
    )

    assert (
        mutated.profile.normalized_score()
        >
        base.profile.normalized_score()
    )

    assert len(
        mutated.events
    ) > len(
        base.events
    )


def test_environment_complexity_feeds_txq():
    objective = "repair service"

    easy = choose_txq_policy(
        objective,
        environment_profile=(
            EnvironmentProfile()
        ),
    )

    hard = choose_txq_policy(
        objective,
        environment_profile=(
            EnvironmentProfile(
                action_depth=5,
                event_rate=10,
                ambiguity=1,
                noise=1,
                app_count=8,
                temporal_pressure=1,
                actor_count=8,
                hidden_state=1,
            )
        ),
    )

    assert (
        hard.difficulty
        >= easy.difficulty
    )

    assert (
        hard.quality_target
        >= easy.quality_target
    )


def test_gaia2_adapter():
    scenario = (
        scenario_from_gaia2_record(
            {
                "id":
                    "gaia2-demo",
                "task":
                    "reply before deadline",
                "initial_state": {
                    "replied":
                        False,
                },
                "events": [
                    {
                        "id":
                            "message",
                        "time":
                            2.0,
                        "type":
                            "message",
                        "payload": {
                            "operation":
                                "merge",
                            "data": {
                                "message":
                                    "hello"
                            },
                        },
                    }
                ],
                "apps": [
                    "mail",
                    "calendar",
                ],
                "actors": [
                    "user",
                    "agent",
                ],
                "dimensions": {
                    "ambiguity":
                        0.4,
                    "temporal_pressure":
                        0.8,
                },
            }
        )
    )

    assert (
        scenario.scenario_id
        == "gaia2-demo"
    )

    assert len(
        scenario.events
    ) == 1

    assert (
        scenario.profile.app_count
        == 2
    )


def test_trace_persistence(
    tmp_path: Path,
):
    scenario = Scenario(
        scenario_id="trace",
        objective="trace",
    )

    env = ResearchEnvironment(
        scenario
    )

    env.advance(
        1
    )

    path = save_trace(
        env,
        tmp_path
        / "trace.json",
    )

    assert path.is_file()

    assert (
        "trace"
        in path.read_text(
            encoding="utf-8"
        )
    )


def test_world_updates_explicit_execution_state():
    scenario = Scenario(
        scenario_id="explicit-state",
        objective="track changing world",
        initial_state={
            "status": "idle",
        },
        events=(
            EnvironmentEvent(
                event_id="wake",
                at=2.0,
                kind="status_change",
                payload={
                    "operation":
                        "merge",
                    "data": {
                        "status":
                            "active",
                    },
                },
            ),
        ),
    )

    env = ResearchEnvironment(
        scenario
    )

    before = (
        env.execution_state.state_digest
    )

    env.advance(
        2.0
    )

    assert (
        env.execution_state.state[
            "status"
        ]
        == "active"
    )

    assert (
        env.execution_state.state_digest
        != before
    )

    assert (
        env.execution_state.latest_observation
        is not None
    )


def test_world_model_context_does_not_embed_full_trace():
    scenario = Scenario(
        scenario_id="no-transcript",
        objective="remain bounded",
        initial_state={
            "count": 0,
        },
    )

    env = ResearchEnvironment(
        scenario
    )

    for index in range(30):
        env.act(
            EnvironmentAction(
                actor="tester",
                action="set",
                payload={
                    "operation":
                        "set",
                    "key":
                        "count",
                    "value":
                        index,
                },
            )
        )

    context = (
        env.execution_state.model_context()
    )

    assert (
        context[
            "current_state"
        ][
            "count"
        ]
        == 29
    )

    assert (
        "trace"
        not in context
    )
