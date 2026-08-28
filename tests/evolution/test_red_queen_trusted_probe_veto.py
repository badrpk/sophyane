from __future__ import annotations

import ast
from pathlib import Path

from sophyane.evolution.engine import (
    EvolutionEngine,
)
from sophyane.evolution.models import (
    EvolutionConfig,
    GateResult,
)


def engine(
    tmp_path: Path,
) -> EvolutionEngine:
    repo = tmp_path / "repo"
    repo.mkdir()

    return EvolutionEngine(
        EvolutionConfig(
            repo=repo,
            cycles=4,
            timeout_seconds=10,
            allow_candidate_patches=False,
            allow_promotion=False,
        )
    )


def gate(
    *,
    promotable: bool,
    probes=None,
) -> GateResult:
    details = {
        "candidate_generalization_score":
            1.0,
        "candidate_generalization": {
            "executed": True,
        },
    }

    if probes is not None:
        details[
            "red_queen_native_probes"
        ] = probes

    return GateResult(
        targeted_passed=True,
        regression_passed=True,
        held_out_passed=True,
        baseline_score=1.0,
        candidate_score=1.0,
        security_passed=True,
        promotable=promotable,
        details=details,
    )


def failed_probe():
    return {
        "family": "targeted",
        "challenge_id":
            "red-queen::targeted::supplemental-v1",
        "test":
            "tests/red_queen/test_targeted_supplemental.py",
        "executed": True,
        "passed": False,
        "returncode": 1,
    }


def passed_probe():
    return {
        "family": "targeted",
        "challenge_id":
            "red-queen::targeted::supplemental-v1",
        "test":
            "tests/red_queen/test_targeted_supplemental.py",
        "executed": True,
        "passed": True,
        "returncode": 0,
    }


def missing_probe():
    return {
        "family": "targeted",
        "challenge_id":
            "red-queen::targeted::supplemental-v1",
        "test":
            "tests/red_queen/test_targeted_supplemental.py",
        "executed": False,
        "passed": None,
        "returncode": None,
    }


def test_failed_executed_probe_vetoes_true_gate(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
        probes=[
            failed_probe()
        ],
    )

    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is True
    assert current.promotable is False

    assert (
        current.details[
            "red_queen_trusted_probe_veto"
        ]
        is True
    )

    assert (
        current.details[
            "red_queen_pre_veto_promotable"
        ]
        is True
    )

    assert (
        current.details[
            "red_queen_post_veto_promotable"
        ]
        is False
    )


def test_veto_can_never_promote_false_gate(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=False,
        probes=[
            passed_probe()
        ],
    )

    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is False
    assert current.promotable is False


def test_passed_probe_does_not_veto(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
        probes=[
            passed_probe()
        ],
    )

    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is False
    assert current.promotable is True


def test_missing_probe_does_not_veto(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
        probes=[
            missing_probe()
        ],
    )

    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is False
    assert current.promotable is True


def test_absent_probe_evidence_does_not_veto(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
    )

    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is False
    assert current.promotable is True


def test_evaluator_metadata_alone_cannot_veto(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
    )

    current.details[
        "red_queen_native_probe_detected"
    ] = True

    # Boolean metadata is not sufficient authority.
    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is False
    assert current.promotable is True


def test_timeout_is_executed_failure_and_vetoes(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
        probes=[
            {
                **failed_probe(),
                "returncode": None,
                "timeout": True,
            }
        ],
    )

    vetoed = (
        item
        ._apply_trusted_red_queen_probe_veto(
            current
        )
    )

    assert vetoed is True
    assert current.promotable is False

    reasons = current.details[
        "red_queen_trusted_probe_veto_reasons"
    ]

    assert reasons
    assert reasons[0]["timeout"] is True


def test_veto_does_not_modify_other_gate_booleans(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    current = gate(
        promotable=True,
        probes=[
            failed_probe()
        ],
    )

    before = (
        current.targeted_passed,
        current.regression_passed,
        current.held_out_passed,
        current.security_passed,
    )

    item._apply_trusted_red_queen_probe_veto(
        current
    )

    after = (
        current.targeted_passed,
        current.regression_passed,
        current.held_out_passed,
        current.security_passed,
    )

    assert before == after
    assert current.promotable is False


def test_cycle_order_is_gate_probe_veto_attribution_write():
    import sophyane.evolution.engine as module

    path = Path(
        module.__file__
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        )
    )

    cycle = next(
        node
        for node in ast.walk(tree)
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "cycle"
        )
    )

    calls = []

    for node in ast.walk(cycle):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if isinstance(
            node.func,
            ast.Attribute,
        ):
            calls.append(
                (
                    node.lineno,
                    node.func.attr,
                )
            )

    calls.sort()

    gate_line = next(
        line
        for line, name in calls
        if name == "_gate"
    )

    probe_line = next(
        line
        for line, name in calls
        if name
        == "_run_red_queen_native_challenges"
    )

    veto_line = next(
        line
        for line, name in calls
        if name
        == "_apply_trusted_red_queen_probe_veto"
    )

    rq_line = next(
        line
        for line, name in calls
        if name
        == "_red_queen_attribution"
    )

    write_line = next(
        line
        for line, name in calls
        if name == "write"
    )

    assert (
        gate_line
        < probe_line
        < veto_line
        < rq_line
        < write_line
    )
