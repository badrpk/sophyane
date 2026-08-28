from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def init_repo(
    root: Path,
) -> Path:
    repo = root / "repo"
    repo.mkdir()

    subprocess.run(
        [
            "git",
            "init",
            "-q",
        ],
        cwd=repo,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "rq8@example.invalid",
        ],
        cwd=repo,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "RQ8 Test",
        ],
        cwd=repo,
        check=True,
    )

    (repo / "base.txt").write_text(
        "base\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "git",
            "add",
            "-A",
        ],
        cwd=repo,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "commit",
            "-qm",
            "base",
        ],
        cwd=repo,
        check=True,
    )

    return repo


def engine(
    repo: Path,
    *,
    allow_promotion: bool = True,
) -> EvolutionEngine:
    return EvolutionEngine(
        EvolutionConfig(
            repo=repo,
            cycles=2,
            allow_candidate_patches=True,
            allow_promotion=allow_promotion,
        )
    )


def record(
    workspace: Path,
    *,
    promotable: bool,
) -> EvolutionRecord:
    item = EvolutionRecord(
        run_id="rq8",
        cycle=1,
        task=TaskSpec(
            task_id="rq8",
            prompt="rq8",
            capability="python",
            validator="pytest",
            held_out=True,
        ),
        trace=ExecutionTrace(
            task_id="rq8",
            workspace=str(
                workspace
            ),
            command=["python"],
            exit_code=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        ),
        validation=ValidationResult(
            passed=True,
            validator="pytest",
            checks={},
            errors=[],
        ),
    )

    item.proposal = SimpleNamespace(
        component="rq8",
    )

    item.gate = GateResult(
        targeted_passed=True,
        regression_passed=True,
        held_out_passed=True,
        baseline_score=1.0,
        candidate_score=3.0,
        security_passed=True,
        promotable=promotable,
        details={
            "worktree": str(
                workspace
            ),
            "promotion_committed": False,
        },
    )

    return item


def test_deferred_promotion_commits_real_worktree(
    tmp_path,
):
    repo = init_repo(
        tmp_path
    )

    workspace = (
        tmp_path
        / "candidate"
    )

    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            str(repo),
            str(workspace),
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "rq8@example.invalid",
        ],
        cwd=workspace,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "RQ8 Test",
        ],
        cwd=workspace,
        check=True,
    )

    (
        workspace / "base.txt"
    ).write_text(
        "candidate\n",
        encoding="utf-8",
    )

    current = record(
        workspace,
        promotable=True,
    )

    before = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=workspace,
        text=True,
    ).strip()

    item = engine(
        repo
    )

    promoted = (
        item
        ._promote_after_trusted_red_queen_veto(
            current
        )
    )

    after = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=workspace,
        text=True,
    ).strip()

    assert promoted is True
    assert after != before

    assert (
        current.gate.details[
            "promotion_committed"
        ]
        is True
    )


def test_vetoed_candidate_cannot_commit(
    tmp_path,
):
    repo = init_repo(
        tmp_path
    )

    workspace = (
        tmp_path
        / "candidate"
    )

    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            str(repo),
            str(workspace),
        ],
        check=True,
    )

    (
        workspace / "base.txt"
    ).write_text(
        "bad candidate\n",
        encoding="utf-8",
    )

    current = record(
        workspace,
        promotable=False,
    )

    before = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=workspace,
        text=True,
    ).strip()

    item = engine(
        repo
    )

    promoted = (
        item
        ._promote_after_trusted_red_queen_veto(
            current
        )
    )

    after = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=workspace,
        text=True,
    ).strip()

    assert promoted is False
    assert after == before
    assert current.gate.promotable is False


def test_false_gate_can_never_be_upgraded(
    tmp_path,
):
    repo = init_repo(
        tmp_path
    )

    current = record(
        repo,
        promotable=False,
    )

    item = engine(
        repo
    )

    assert (
        item
        ._promote_after_trusted_red_queen_veto(
            current
        )
        is False
    )

    assert current.gate.promotable is False


def test_cycle_order_places_commit_boundary_after_veto():
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

    names = {
        name: line
        for line, name in calls
        if name in {
            "_gate",
            "_run_red_queen_native_challenges",
            "_apply_trusted_red_queen_probe_veto",
            "_promote_after_trusted_red_queen_veto",
            "_red_queen_attribution",
            "write",
        }
    }

    assert (
        names["_gate"]
        < names[
            "_run_red_queen_native_challenges"
        ]
        < names[
            "_apply_trusted_red_queen_probe_veto"
        ]
        < names[
            "_promote_after_trusted_red_queen_veto"
        ]
        < names[
            "_red_queen_attribution"
        ]
        < names["write"]
    )


def test_cycle_uses_defer_promotion_true():
    import sophyane.evolution.engine as module

    text = Path(
        module.__file__
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(text)

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

    gate_calls = []

    for node in ast.walk(cycle):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if not isinstance(
            node.func,
            ast.Attribute,
        ):
            continue

        if node.func.attr != "_gate":
            continue

        gate_calls.append(node)

    assert len(gate_calls) == 1

    call = gate_calls[0]

    values = {
        keyword.arg:
            keyword.value
        for keyword in call.keywords
        if keyword.arg
    }

    assert "defer_promotion" in values

    value = values[
        "defer_promotion"
    ]

    assert isinstance(
        value,
        ast.Constant,
    )

    assert value.value is True


def test_direct_gate_default_remains_backward_compatible():
    import inspect

    signature = inspect.signature(
        EvolutionEngine._gate
    )

    parameter = signature.parameters[
        "defer_promotion"
    ]

    assert parameter.default is False
