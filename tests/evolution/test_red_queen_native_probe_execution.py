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
    workspace: Path,
    *,
    promotable: bool = True,
) -> GateResult:
    return GateResult(
        targeted_passed=True,
        regression_passed=True,
        held_out_passed=True,
        baseline_score=1.0,
        candidate_score=1.0,
        security_passed=True,
        promotable=promotable,
        details={
            "worktree": str(
                workspace
            ),
            "candidate_generalization_score":
                1.0,
            "candidate_generalization": {
                "executed": True,
            },
        },
    )


def make_workspace(
    tmp_path: Path,
) -> Path:
    workspace = (
        tmp_path
        / "candidate"
    )

    package = (
        workspace
        / "src"
        / "rq6app"
    )

    tests = (
        workspace
        / "tests"
        / "red_queen"
    )

    package.mkdir(
        parents=True,
    )

    tests.mkdir(
        parents=True,
    )

    (
        package
        / "__init__.py"
    ).write_text(
        "",
        encoding="utf-8",
    )

    (
        package
        / "core.py"
    ).write_text(
        '''\
def normalize(value: str) -> str:
    return value.lower()
''',
        encoding="utf-8",
    )

    return workspace


def teach_targeted(
    item: EvolutionEngine,
) -> None:
    item.red_queen_execution_policy.learn(
        failures=(
            "targeted validation failure",
        ),
        epoch=2,
        evaluator_identity=(
            item.red_queen
            .active.identity()
        ),
    )


def test_no_policy_requests_means_no_execution(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    workspace = make_workspace(
        tmp_path
    )

    current = gate(
        workspace
    )

    before = current.promotable

    evidence = (
        item
        ._run_red_queen_native_challenges(
            current
        )
    )

    assert evidence == ()

    assert (
        current.promotable
        is before
    )

    assert (
        current.details[
            "red_queen_native_probe_detected"
        ]
        is False
    )


def test_missing_supplemental_test_is_safe_skip(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    teach_targeted(
        item
    )

    workspace = make_workspace(
        tmp_path
    )

    current = gate(
        workspace
    )

    evidence = (
        item
        ._run_red_queen_native_challenges(
            current
        )
    )

    assert len(evidence) == 1

    assert (
        evidence[0]["executed"]
        is False
    )

    assert (
        current.details[
            "red_queen_native_probe_count"
        ]
        == 0
    )


def test_real_supplemental_pytest_failure_is_detected(
    tmp_path,
    monkeypatch,
):
    item = engine(
        tmp_path
    )

    teach_targeted(
        item
    )

    workspace = make_workspace(
        tmp_path
    )

    test_file = (
        workspace
        / "tests"
        / "red_queen"
        / "test_targeted_supplemental.py"
    )

    test_file.write_text(
        '''\
from rq6app.core import normalize


def test_whitespace():
    assert normalize(" Alice ") == "alice"
''',
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "PYTHONPATH",
        str(
            workspace / "src"
        ),
    )

    current = gate(
        workspace,
        promotable=True,
    )

    before = current.promotable

    evidence = (
        item
        ._run_red_queen_native_challenges(
            current
        )
    )

    assert len(evidence) == 1

    assert (
        evidence[0]["executed"]
        is True
    )

    assert (
        evidence[0]["passed"]
        is False
    )

    assert (
        current.details[
            "red_queen_native_probe_detected"
        ]
        is True
    )

    assert (
        current.details[
            "red_queen_native_probe_count"
        ]
        == 1
    )

    # Absolute RQ6 source-authority invariant.
    assert current.promotable is before
    assert current.promotable is True


def test_real_supplemental_pytest_pass_is_recorded(
    tmp_path,
    monkeypatch,
):
    item = engine(
        tmp_path
    )

    teach_targeted(
        item
    )

    workspace = make_workspace(
        tmp_path
    )

    test_file = (
        workspace
        / "tests"
        / "red_queen"
        / "test_targeted_supplemental.py"
    )

    test_file.write_text(
        '''\
from rq6app.core import normalize


def test_basic():
    assert normalize("Alice") == "alice"
''',
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "PYTHONPATH",
        str(
            workspace / "src"
        ),
    )

    current = gate(
        workspace
    )

    evidence = (
        item
        ._run_red_queen_native_challenges(
            current
        )
    )

    assert len(evidence) == 1

    assert (
        evidence[0]["passed"]
        is True
    )

    assert (
        current.details[
            "red_queen_native_probe_detected"
        ]
        is False
    )


def test_request_cannot_supply_arbitrary_command(
    tmp_path,
):
    item = engine(
        tmp_path
    )

    teach_targeted(
        item
    )

    request = (
        item.red_queen_challenges()[0]
    )

    assert not hasattr(
        request,
        "command",
    )

    assert not hasattr(
        request,
        "path",
    )

    assert (
        request.family
        == "targeted"
    )


def test_native_probe_does_not_modify_gate_booleans(
    tmp_path,
    monkeypatch,
):
    item = engine(
        tmp_path
    )

    teach_targeted(
        item
    )

    workspace = make_workspace(
        tmp_path
    )

    (
        workspace
        / "tests"
        / "red_queen"
        / "test_targeted_supplemental.py"
    ).write_text(
        '''\
def test_failure():
    assert False
''',
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "PYTHONPATH",
        str(
            workspace / "src"
        ),
    )

    current = gate(
        workspace,
        promotable=True,
    )

    authority = (
        current.targeted_passed,
        current.regression_passed,
        current.held_out_passed,
        current.security_passed,
        current.promotable,
    )

    item._run_red_queen_native_challenges(
        current
    )

    assert (
        current.targeted_passed,
        current.regression_passed,
        current.held_out_passed,
        current.security_passed,
        current.promotable,
    ) == authority


def test_real_cycle_order_is_gate_probe_attribution_write():
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

    for node in ast.walk(
        cycle
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        func = node.func

        if isinstance(
            func,
            ast.Attribute,
        ):
            calls.append(
                (
                    node.lineno,
                    func.attr,
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

    attribution_line = next(
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
        < attribution_line
        < write_line
    )
