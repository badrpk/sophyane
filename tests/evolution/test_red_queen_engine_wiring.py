from __future__ import annotations

import json
from dataclasses import asdict
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


def task() -> TaskSpec:
    return TaskSpec(
        task_id="rq2-task",
        prompt="test prompt",
        capability="python",
        validator="pytest",
        held_out=True,
    )


def trace() -> ExecutionTrace:
    return ExecutionTrace(
        task_id="rq2-task",
        workspace="/tmp/rq2",
        command=["python"],
        exit_code=1,
        stdout="",
        stderr="",
        elapsed_seconds=0.1,
    )


def validation() -> ValidationResult:
    return ValidationResult(
        passed=False,
        validator="pytest",
        checks={
            "objective": False,
        },
        errors=["failure"],
    )


def record() -> EvolutionRecord:
    return EvolutionRecord(
        run_id="rq2-run",
        cycle=1,
        task=task(),
        trace=trace(),
        validation=validation(),
    )


def engine(tmp_path: Path) -> EvolutionEngine:
    repo = tmp_path / "repo"
    repo.mkdir()

    item = EvolutionEngine(
        EvolutionConfig(
            repo=repo,
            cycles=2,
            allow_candidate_patches=False,
            allow_promotion=False,
        )
    )

    return item


def executed_gate(
    *,
    promotable: bool = False,
    anchor_score: float = 0.95,
    targeted: bool = False,
    regression: bool = True,
    security: bool = True,
    held_out: bool = True,
) -> GateResult:
    return GateResult(
        targeted_passed=targeted,
        regression_passed=regression,
        held_out_passed=held_out,
        baseline_score=0.80,
        candidate_score=2.0,
        security_passed=security,
        promotable=promotable,
        details={
            "candidate_generalization_score":
                anchor_score,
            "candidate_generalization": {
                "executed": True,
            },
        },
    )


def test_engine_owns_explicit_red_queen_state(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    assert (
        item.red_queen.epoch
        == 1
    )

    assert (
        item.red_queen.active.version
        == 1
    )

    assert (
        item.red_queen.trusted_anchor_id
        == "sophyane-heldout-anchor-v1"
    )


def test_record_fields_are_default_compatible():
    item = record()

    assert item.evaluator_id == ""
    assert item.evaluator_version == 0
    assert item.evaluator_identity == ""
    assert item.evaluator_epoch == 0
    assert (
        item.evaluator_promotion_accepted
        is False
    )
    assert item.trusted_anchor_score is None


def test_old_style_record_serialization_still_works():
    payload = asdict(
        record()
    )

    encoded = json.dumps(
        payload
    )

    assert '"run_id": "rq2-run"' in encoded
    assert '"evaluator_id": ""' in encoded


def test_real_gate_anchor_is_attributed(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = record()
    current.gate = executed_gate(
        anchor_score=0.97,
        targeted=False,
    )

    item._red_queen_attribution(
        current
    )

    assert (
        current.trusted_anchor_score
        == 0.97
    )

    assert current.evaluator_id
    assert current.evaluator_version == 1
    assert len(
        current.evaluator_identity
    ) == 64
    assert current.evaluator_epoch == 1


def test_red_queen_cannot_upgrade_gate_promotable(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = record()
    current.gate = executed_gate(
        promotable=False,
        anchor_score=1.0,
        targeted=False,
    )

    before = (
        current.gate.promotable
    )

    item._red_queen_attribution(
        current
    )

    assert (
        current.gate.promotable
        is before
    )

    assert (
        current.gate.promotable
        is False
    )


def test_failed_anchor_blocks_evaluator_promotion(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = record()
    current.gate = executed_gate(
        anchor_score=0.50,
        targeted=False,
        held_out=False,
    )

    item._red_queen_attribution(
        current
    )

    assert (
        current.evaluator_promotion_accepted
        is False
    )

    assert (
        item.red_queen.epoch
        == 1
    )

    assert "anchor" in (
        current.evaluator_promotion_reason
    )


def test_passing_gate_does_not_manufacture_challenger(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = record()
    current.gate = executed_gate(
        promotable=True,
        anchor_score=1.0,
        targeted=True,
        regression=True,
        security=True,
        held_out=True,
    )

    item._red_queen_attribution(
        current
    )

    assert not (
        item.red_queen.challengers
    )

    assert (
        item.red_queen.epoch
        == 1
    )

    assert (
        current.evaluator_promotion_accepted
        is False
    )

    assert (
        current.evaluator_promotion_reason
        == "no observed evaluator blind spot"
    )

    # Existing source gate remains independently true.
    assert current.gate.promotable is True


def test_winning_challenger_changes_evaluator_not_source_gate(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = record()
    current.gate = executed_gate(
        promotable=False,
        anchor_score=0.99,
        targeted=False,
        regression=True,
        security=True,
        held_out=True,
    )

    item._red_queen_attribution(
        current
    )

    assert (
        current.evaluator_promotion_accepted
        is True
    )

    assert item.red_queen.epoch == 2

    assert (
        item.red_queen.active.version
        == 2
    )

    assert (
        current.gate.promotable
        is False
    )


def test_retired_evaluator_utility_only_is_invalidated(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    first = record()
    first.gate = executed_gate(
        promotable=False,
        anchor_score=0.99,
        targeted=False,
    )

    old_identity = (
        item.red_queen.active.identity()
    )

    item._red_queen_attribution(
        first
    )

    assert (
        old_identity
        in item.red_queen.ledger
        .invalidated_identities
    )

    valid = (
        item.red_queen.ledger
        .valid_records()
    )

    assert all(
        outcome.evaluator_identity
        != old_identity
        for outcome in valid
    )


def test_red_queen_epochs_are_bounded_by_engine_cycles(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    assert item.config.cycles == 2

    for index in range(
        item.config.cycles
    ):
        current = record()
        current.run_id = (
            f"run-{index}"
        )

        current.gate = executed_gate(
            promotable=False,
            anchor_score=0.99,
            targeted=False,
        )

        item._red_queen_attribution(
            current
        )

    # Initial epoch plus no more than one evaluator transition
    # for each bounded engine cycle.
    assert (
        item.red_queen.epoch
        <= item.config.cycles + 1
    )


def test_trusted_anchor_is_not_active_evaluator(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    assert (
        item.red_queen.trusted_anchor_id
        != item.red_queen.active.evaluator_id
    )


def test_record_write_persists_evaluator_provenance(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = record()
    current.gate = executed_gate(
        anchor_score=0.95,
        targeted=True,
    )

    item._red_queen_attribution(
        current
    )

    path = current.write(
        tmp_path
        / "records"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert payload[
        "evaluator_id"
    ]

    assert payload[
        "evaluator_version"
    ] == 1

    assert len(
        payload[
            "evaluator_identity"
        ]
    ) == 64

    assert (
        payload[
            "trusted_anchor_score"
        ]
        == 0.95
    )
