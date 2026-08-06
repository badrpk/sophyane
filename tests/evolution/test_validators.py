from pathlib import Path

from sophyane.evolution.models import (
    ExecutionTrace,
    TaskSpec,
)
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
