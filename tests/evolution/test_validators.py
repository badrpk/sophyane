from pathlib import Path

from sophyane.evolution.models import (
    EvolutionConfig,
    ExecutionTrace,
    TaskSpec,
)
from sophyane.evolution.engine import EvolutionEngine
from sophyane.evolution.validators import (
    validate,
)


def _trace(
    workspace: Path,
    output: str = "",
) -> ExecutionTrace:
    return ExecutionTrace(
        task_id="task",
        workspace=str(workspace),
        command=["sophyane"],
        exit_code=0,
        stdout=output,
        stderr="",
        elapsed_seconds=0.1,
        files=[],
    )


def test_html_validator(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text(
        """<!doctype html>
<html><body>
<label for="q">Search</label>
<input id="q">
<button id="b">Go</button>
<script>
document.getElementById("b")
.addEventListener("click", () => {});
</script>
</body></html>
""",
        encoding="utf-8",
    )

    result = validate(
        TaskSpec(
            task_id="html",
            prompt="build",
            capability="html",
            validator="html",
        ),
        _trace(tmp_path),
    )

    assert result.passed is True


def test_semantic_validator_blocks_public_route(
    tmp_path: Path,
) -> None:
    result = validate(
        TaskSpec(
            task_id="semantic",
            prompt="personal",
            capability="semantic_routing",
            validator="semantic_routing",
        ),
        _trace(
            tmp_path,
            (
                "Semantic domain: personal_knowledge\n"
                "Public internet fallback: blocked"
            ),
        ),
    )

    assert result.passed is True


def test_native_evolution_uses_deterministic_shell_executor(tmp_path: Path) -> None:
    engine = EvolutionEngine.__new__(EvolutionEngine)
    repository = Path.cwd()
    engine.repo = repository
    engine.config = EvolutionConfig(repo=repository, timeout_seconds=30)

    trace = engine._run_sli(
        TaskSpec(
            task_id="shell-focused-00001",
            prompt=(
                "Create exit_probe.sh that prints STDOUT_OK to stdout, "
                "STDERR_OK to stderr, exits with code 7, runs it, and "
                "reports the real stdout, stderr and exit code."
            ),
            capability="shell",
            validator="shell",
        )
    )

    assert validate(
        TaskSpec("shell", "", "shell", "shell"),
        trace,
    ).passed is True


def test_native_evolution_uses_local_python_executor(tmp_path: Path) -> None:
    engine = EvolutionEngine.__new__(EvolutionEngine)
    repository = Path.cwd()
    engine.repo = repository
    engine.config = EvolutionConfig(repo=repository, timeout_seconds=30)

    trace = engine._run_sli(
        TaskSpec(
            task_id="python-focused-00001",
            prompt=(
                "Create calc.py with add(a, b). Create and run a pytest "
                "test proving add(20, 22) equals 42."
            ),
            capability="python",
            validator="python",
        )
    )

    assert validate(
        TaskSpec("python", "", "python", "python"),
        trace,
    ).passed is True
    assert trace.elapsed_seconds > 0.0
