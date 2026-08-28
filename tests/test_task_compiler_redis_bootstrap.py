from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    compile_task,
)
from sophyane.task_executor import (
    execute_compiled_task,
)


PROMPT = (
    "Implement a sliding-window rate-limiting middleware using Redis "
    "and Lua scripts to restrict unauthenticated users to 100 req/min "
    "per IP. Return 429 Too Many Requests with Retry-After and "
    "X-RateLimit-* headers upon violation."
)


def test_no_target_compiles_to_deterministic_bootstrap(
    tmp_path: Path,
) -> None:
    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert result.handled
    assert result.ok
    assert result.unresolved == []

    assert len(
        result.execution_plan
    ) == 1

    step = result.execution_plan[
        0
    ]

    assert (
        step["operation"]
        == "modify_http_rate_limit_middleware"
    )

    assert [
        target["path"]
        for target in step[
            "targets"
        ]
    ] == [
        "app/middleware.py"
    ]

    grounding = result.groundings[
        "r1"
    ][0]

    assert (
        grounding.evidence
        == (
            "bootstrap:new-http-middleware;"
            "contract:redis_sliding_window_rate_limit"
        )
    )


def test_bootstrap_execution_creates_real_middleware(
    tmp_path: Path,
) -> None:
    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok
    assert result.steps
    assert result.steps[0].ok
    assert result.steps[0].mutated

    path = (
        tmp_path
        / "app"
        / "middleware.py"
    )

    assert path.is_file()

    text = path.read_text(
        encoding="utf-8",
    )

    for token in (
        "SOPHYANE_REDIS_SLIDING_WINDOW_RATE_LIMIT_V1",
        "ZREMRANGEBYSCORE",
        "ZCARD",
        "ZADD",
        "PEXPIRE",
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    ):
        assert token in text

    assert "INCR" not in text.upper()


def test_bootstrap_is_idempotent(
    tmp_path: Path,
) -> None:
    first_compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    first = execute_compiled_task(
        first_compiled,
        workspace=tmp_path,
    )

    assert first.ok

    path = (
        tmp_path
        / "app"
        / "middleware.py"
    )

    before = path.read_bytes()

    second_compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    second = execute_compiled_task(
        second_compiled,
        workspace=tmp_path,
    )

    assert second.ok
    assert path.read_bytes() == before


def test_existing_unrelated_files_are_never_bootstrap_targets(
    tmp_path: Path,
) -> None:
    unrelated = (
        tmp_path
        / "policy.py"
    )

    unrelated.write_text(
        """
REDIS_URL = "redis://localhost"
request = "middleware request"
""".lstrip(),
        encoding="utf-8",
    )

    before = unrelated.read_bytes()

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.ok

    paths = {
        target["path"]
        for step in compiled.execution_plan
        for target in step["targets"]
    }

    assert paths == {
        "app/middleware.py"
    }

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok
    assert unrelated.read_bytes() == before
