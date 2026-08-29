from pathlib import Path

from sophyane.mode3_meta_rsi import (
    MetaProposal,
    accept_meta_proposal,
    apply_txq_to_instruction,
    bounded_episode_limit,
    build_nifdu_meta_context,
    choose_txq_policy,
    load_state,
    observation_identity,
    parse_meta_proposal,
    record_observation,
)


def test_txq_harder_task_gets_more_budget() -> None:
    easy = choose_txq_policy(
        "create hello.py"
    )

    hard = choose_txq_policy(
        "Repair a distributed asynchronous transaction "
        "race condition with held-out regression tests."
    )

    assert (
        hard.difficulty
        > easy.difficulty
    )

    assert (
        hard.context_budget_chars
        >= easy.context_budget_chars
    )

    assert (
        hard.verification_depth
        >= easy.verification_depth
    )


def test_txq_instruction_contains_bounded_policy() -> None:
    rendered, policy = (
        apply_txq_to_instruction(
            "repair parser",
            objective="repair parser",
        )
    )

    assert "MODE3_TXQ_POLICY" in rendered
    assert "truth_policy=" in rendered

    assert (
        policy.wall_time_budget_sec
        <= 600
    )

    assert (
        policy.retry_budget
        <= 2
    )


def test_episode_limit_is_hard_bounded() -> None:
    assert bounded_episode_limit(1) == 1

    assert (
        bounded_episode_limit(999)
        == 12
    )


def test_same_candidate_has_same_observation_identity() -> None:
    first = observation_identity(
        objective="repair parser",
        candidate_diff="+return parsed\n",
        verification_commands=(
            "pytest -q",
        ),
    )

    second = observation_identity(
        objective="repair parser",
        candidate_diff="+return parsed\n",
        verification_commands=(
            "pytest -q",
        ),
    )

    assert first == second


def test_material_candidate_change_is_new_observation() -> None:
    first = observation_identity(
        objective="repair parser",
        candidate_diff="+return first\n",
        verification_commands=(
            "pytest -q",
        ),
    )

    second = observation_identity(
        objective="repair parser",
        candidate_diff="+return second\n",
        verification_commands=(
            "pytest -q",
        ),
    )

    assert first != second


def test_retry_does_not_double_count_txq_learning(
    tmp_path: Path,
) -> None:
    state_path = (
        tmp_path
        / "state.json"
    )

    policy = choose_txq_policy(
        "repair parser",
        state={
            "version": 1,
            "families": {},
            "observations": {},
            "accepted_meta_proposals": [],
        },
    )

    common = {
        "objective": "repair parser",
        "policy": policy,
        "candidate_diff": "+return parsed\n",
        "verification_commands": (
            "pytest -q",
        ),
        "elapsed_sec": 2.0,
        "verification_ok": True,
        "held_out_attempted": True,
        "held_out_not_regressed": True,
        "nifdu_status": "SUCCESS",
        "retry_index": 1,
        "state_path": state_path,
    }

    _, first_new = record_observation(
        **common
    )

    _, second_new = record_observation(
        **common
    )

    assert first_new is True
    assert second_new is False

    state = load_state(
        state_path
    )

    family = state[
        "families"
    ][
        "debugging"
    ]

    assert family[
        "attempts"
    ] == 1

    assert family[
        "successes"
    ] == 1


def test_nifdu_meta_context_does_not_grant_truth() -> None:
    policy = choose_txq_policy(
        "repair parser"
    )

    text = build_nifdu_meta_context(
        objective="repair parser",
        policy=policy,
        elapsed_sec=3.0,
        verification_ok=False,
        held_out_attempted=False,
        held_out_not_regressed=True,
        failure="tests failed",
    )

    assert (
        "deterministic evidence"
        in text
    )

    assert (
        "Do not replace deterministic verification"
        in text
    )


def test_parse_valid_meta_proposal() -> None:
    response = (
        "STATUS: CONTINUE\n"
        "META_RSI_JSON: "
        '{"target":"prompt_policy",'
        '"hypothesis":"weak model needs smaller steps",'
        '"proposed_change":"split coding request into two bounded stages",'
        '"expected_time_delta":0.1,'
        '"expected_quality_delta":0.2,'
        '"expected_success_delta":0.3,'
        '"risk":"low",'
        '"rollback_condition":"held-out score decreases"}'
    )

    proposal = parse_meta_proposal(
        response
    )

    assert proposal is not None

    assert (
        proposal.target
        == "prompt_policy"
    )


def test_invalid_meta_target_is_rejected() -> None:
    response = (
        "META_RSI_JSON: "
        '{"target":"git_push",'
        '"hypothesis":"x",'
        '"proposed_change":"y"}'
    )

    assert (
        parse_meta_proposal(
            response
        )
        is None
    )


def test_meta_advice_requires_real_verification(
    tmp_path: Path,
) -> None:
    proposal = MetaProposal(
        target="context",
        hypothesis="more focused context",
        proposed_change="select failing module only",
    )

    assert (
        accept_meta_proposal(
            proposal,
            deterministic_verification_ok=False,
            held_out_attempted=False,
            held_out_not_regressed=True,
            state_path=(
                tmp_path
                / "state.json"
            ),
        )
        is False
    )


def test_meta_advice_rejected_on_held_out_regression(
    tmp_path: Path,
) -> None:
    proposal = MetaProposal(
        target="routing",
        hypothesis="route differently",
        proposed_change="change routing heuristic",
    )

    assert (
        accept_meta_proposal(
            proposal,
            deterministic_verification_ok=True,
            held_out_attempted=True,
            held_out_not_regressed=False,
            state_path=(
                tmp_path
                / "state.json"
            ),
        )
        is False
    )


def test_meta_advice_can_be_recorded_after_real_gates(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "state.json"
    )

    proposal = MetaProposal(
        target="prompt_policy",
        hypothesis="smaller steps improve weak-model reliability",
        proposed_change="decompose complex changes",
    )

    assert (
        accept_meta_proposal(
            proposal,
            deterministic_verification_ok=True,
            held_out_attempted=True,
            held_out_not_regressed=True,
            state_path=path,
        )
        is True
    )

    assert (
        accept_meta_proposal(
            proposal,
            deterministic_verification_ok=True,
            held_out_attempted=True,
            held_out_not_regressed=True,
            state_path=path,
        )
        is False
    )
