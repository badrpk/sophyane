from __future__ import annotations

from pathlib import Path

from sophyane.evolution.engine import (
    EvolutionEngine,
)
from sophyane.evolution.models import (
    EvolutionConfig,
    EvolutionRecord,
    ExecutionTrace,
    GateResult,
    TaskSpec,
    ValidationResult,
)
from sophyane.evolution.red_queen_policy import (
    ChallengeRequest,
    RedQueenExecutionPolicy,
)


def make_engine(
    tmp_path: Path,
) -> EvolutionEngine:
    repo = tmp_path / "repo"
    repo.mkdir()

    return EvolutionEngine(
        EvolutionConfig(
            repo=repo,
            cycles=8,
            allow_candidate_patches=False,
            allow_promotion=False,
        )
    )


def make_record(
    *,
    run_id: str,
    targeted: bool = True,
    regression: bool = True,
    held_out: bool = True,
    security: bool = True,
    anchor: float = 1.0,
) -> EvolutionRecord:
    promotable = (
        targeted
        and regression
        and held_out
        and security
    )

    return EvolutionRecord(
        run_id=run_id,
        cycle=1,
        task=TaskSpec(
            task_id=run_id,
            prompt="rq5",
            capability="python",
            validator="pytest",
            held_out=True,
        ),
        trace=ExecutionTrace(
            task_id=run_id,
            workspace="/tmp/rq5",
            command=["python"],
            exit_code=(
                0 if promotable else 1
            ),
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        ),
        validation=ValidationResult(
            passed=promotable,
            validator="pytest",
            checks={},
            errors=[],
        ),
        gate=GateResult(
            targeted_passed=targeted,
            regression_passed=regression,
            held_out_passed=held_out,
            baseline_score=1.0,
            candidate_score=1.0,
            security_passed=security,
            promotable=promotable,
            details={
                "candidate_generalization_score":
                    anchor,
                "candidate_generalization": {
                    "executed": True,
                },
            },
        ),
    )


def test_policy_starts_empty():
    policy = RedQueenExecutionPolicy()

    assert policy.requests() == ()
    assert policy.learned_families() == ()


def test_policy_is_bounded():
    policy = RedQueenExecutionPolicy(
        max_requests=2
    )

    policy.learn(
        failures=(
            "targeted validation failure",
            "regression validation failure",
            "security validation failure",
        ),
        epoch=2,
        evaluator_identity="abc",
    )

    assert len(
        policy.requests()
    ) == 2


def test_request_is_metadata_only():
    request = ChallengeRequest(
        family="targeted",
        challenge_id=(
            "red-queen::targeted::"
            "supplemental-v1"
        ),
        learned_from_epoch=2,
        evaluator_identity="abc",
    )

    assert not hasattr(
        request,
        "passed",
    )

    assert not hasattr(
        request,
        "promotable",
    )

    assert not hasattr(
        request,
        "command",
    )


def test_engine_starts_without_extra_challenges(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    assert (
        engine.red_queen_challenges()
        == ()
    )


def test_accepted_targeted_failure_teaches_targeted_probe(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    record = make_record(
        run_id="targeted",
        targeted=False,
        held_out=True,
        anchor=0.99,
    )

    before = record.gate.promotable

    engine._red_queen_attribution(
        record
    )

    assert (
        record.gate.promotable
        is before
    )

    families = {
        item.family
        for item in (
            engine.red_queen_challenges()
        )
    }

    assert "targeted" in families


def test_accepted_regression_failure_teaches_regression_probe(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    record = make_record(
        run_id="regression",
        regression=False,
        held_out=True,
        anchor=0.99,
    )

    engine._red_queen_attribution(
        record
    )

    families = {
        item.family
        for item in (
            engine.red_queen_challenges()
        )
    }

    assert "regression" in families


def test_accepted_security_failure_teaches_security_probe(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    record = make_record(
        run_id="security",
        security=False,
        held_out=True,
        anchor=0.99,
    )

    engine._red_queen_attribution(
        record
    )

    families = {
        item.family
        for item in (
            engine.red_queen_challenges()
        )
    }

    assert "security" in families


def test_anchor_veto_does_not_teach_policy(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    record = make_record(
        run_id="heldout",
        held_out=False,
        anchor=0.0,
    )

    engine._red_queen_attribution(
        record
    )

    assert (
        engine.red_queen_challenges()
        == ()
    )


def test_policy_never_upgrades_source_gate(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    record = make_record(
        run_id="source-authority",
        targeted=False,
        anchor=0.99,
    )

    assert record.gate is not None
    assert record.gate.promotable is False

    engine._red_queen_attribution(
        record
    )

    assert record.gate.promotable is False


def test_duplicate_family_is_not_unbounded(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    for index in range(4):
        record = make_record(
            run_id=f"targeted-{index}",
            targeted=False,
            anchor=0.99,
        )

        engine._red_queen_attribution(
            record
        )

    targeted = [
        request
        for request in (
            engine.red_queen_challenges()
        )
        if request.family == "targeted"
    ]

    assert len(targeted) == 1
