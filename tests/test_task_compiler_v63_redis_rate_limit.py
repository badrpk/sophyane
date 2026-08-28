from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Requirement,
    compile_task,
    grounding_required,
    requirement_contract,
)

from sophyane.task_executor import (
    execute_compiled_task,
    executor_catalog,
)


PROMPT = (
    "Implement a sliding-window rate-limiting middleware using Redis "
    "and Lua scripts to restrict unauthenticated users to 100 req/min "
    "per IP. Return 429 Too Many Requests with Retry-After and "
    "X-RateLimit-* headers upon violation."
)


def _write_problem_site(
    root: Path,
) -> Path:
    path = (
        root
        / "app"
        / "middleware.py"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        """
async def rate_limit_middleware(
    request,
    redis_client,
    call_next,
):
    user = getattr(request, "user", None)

    if (
        user is not None
        and getattr(user, "is_authenticated", False)
    ):
        return await call_next(request)

    client_ip = request.client.host
    await redis_client.ping()

    return await call_next(request)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return path


def test_v63_contract_classification():
    requirement = Requirement(
        requirement_id="r1",
        text=PROMPT,
        difficulty=4,
        explicit_facts=(
            "architecture:"
            "redis_sliding_window_rate_limit",
        ),
    )

    assert (
        requirement_contract(
            requirement
        )
        == "redis_sliding_window_rate_limit"
    )

    assert grounding_required(
        requirement
    )


def test_v63_raw_objective_is_one_parent(
    tmp_path: Path,
):
    _write_problem_site(
        tmp_path
    )

    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert result.handled
    assert result.ok
    assert result.unresolved == []

    assert len(
        result.requirements
    ) == 1

    requirement = result.requirements[
        0
    ]

    assert (
        requirement_contract(
            requirement
        )
        == "redis_sliding_window_rate_limit"
    )

    assert (
        "architecture:"
        "redis_sliding_window_rate_limit"
        in requirement.explicit_facts
    )


def test_v63_structural_grounding_and_plan(
    tmp_path: Path,
):
    _write_problem_site(
        tmp_path
    )

    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert result.ok
    assert result.unresolved == []

    assert len(
        result.execution_plan
    ) == 1

    step = result.execution_plan[
        0
    ]

    assert (
        step["contract"]
        == "redis_sliding_window_rate_limit"
    )

    assert (
        step["operation"]
        == "modify_http_rate_limit_middleware"
    )

    assert step[
        "targets"
    ]

    assert any(
        target["path"]
        == "app/middleware.py"
        for target in step[
            "targets"
        ]
    )

    evidence = result.evidence[
        result.requirements[
            0
        ].requirement_id
    ]

    assert evidence.valid
    assert (
        evidence.provenance
        == "GROUNDED_DETERMINISTIC"
    )

    lower = evidence.value.lower()

    for token in (
        "sliding window",
        "redis",
        "lua",
        "100",
        "60 seconds",
        "ip",
        "unauthenticated",
        "429",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ):
        assert token in lower


def test_v63_unrelated_redis_file_does_not_ground(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "redis_config.py"
    )

    path.write_text(
        """
REDIS_URL = "redis://localhost:6379/0"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert result.handled
    assert not result.ok
    assert result.unresolved


def test_v63_phase_b_executor_authority(
    tmp_path: Path,
):
    _write_problem_site(
        tmp_path
    )

    catalog = set(
        executor_catalog()
    )

    assert catalog == {
        "database_analysis",
        "database_index",
        "orm_eager_fetch",
        "circuit_breaker",
        "async_event",
        "idempotency_key",
        "cache_stampede",
        "transactional_outbox",
        "saga_compensation",
        "redis_sliding_window_rate_limit",
    }

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.ok
