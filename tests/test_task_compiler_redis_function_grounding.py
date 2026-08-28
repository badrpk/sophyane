from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    Requirement,
    _structural_grounding_score,
    compile_task,
)


PROMPT = (
    "Implement a sliding-window rate-limiting middleware using Redis "
    "and Lua scripts to restrict unauthenticated users to 100 req/min "
    "per IP. Return 429 Too Many Requests with Retry-After and "
    "X-RateLimit-* headers upon violation."
)


def _requirement() -> Requirement:
    return Requirement(
        requirement_id="r1",
        text=PROMPT,
        difficulty=3,
        explicit_facts=(
            "architecture:"
            "redis_sliding_window_rate_limit",
        ),
    )


def _score(
    relative: str,
    raw: str,
) -> tuple[float, str]:
    return _structural_grounding_score(
        _requirement(),
        relative=relative,
        raw=raw,
        lexical_matches=[
            "redis",
            "request",
        ],
    )


def test_redis_yaml_service_is_not_application_grounding() -> None:
    score, detail = _score(
        ".github/workflows/integration.yml",
        """
services:
  redis:
    image: redis:7
env:
  REDIS_URL: redis://127.0.0.1:6379/0
# request middleware client host
""",
    )

    assert score == 0.0
    assert "not-python" in detail


def test_file_wide_keyword_collision_is_not_grounding() -> None:
    score, detail = _score(
        "routing.py",
        """
SOFTWARE_TERMS = {
    "redis",
    "middleware",
    "request",
    "client",
    "host",
}

def is_execution_request(message):
    return "redis" in message
""",
    )

    assert score == 0.0
    assert "function-scoped" in detail


def test_request_only_function_is_not_grounding() -> None:
    score, detail = _score(
        "acquisition.py",
        """
def acquire_for_request(request):
    text = "redis middleware client host"
    return request
""",
    )

    assert score == 0.0
    assert "function-scoped" in detail


def test_real_middleware_function_is_grounded() -> None:
    score, detail = _score(
        "app/middleware.py",
        """
async def rate_limit_middleware(
    request,
    redis_client,
    call_next,
):
    client_ip = request.client.host
    await redis_client.ping()
    return await call_next(request)
""",
    )

    assert score >= 16.0
    assert "function:rate_limit_middleware" in detail


def test_real_repository_has_no_false_redis_target() -> None:
    root = Path(__file__).resolve().parents[1]

    result = compile_task(
        PROMPT,
        workspace=root,
    )

    refs = result.groundings.get(
        "r1",
        [],
    )

    false_targets = {
        ".github/workflows/integration-compatibility.yml",
        "src/sophyane/code_memory/acquisition_intelligence.py",
        "src/sophyane/harness_task_policy.py",
        "src/sophyane/runtime_intent_refinement_patch.py",
        "src/sophyane/task_executor.py",
        "src/sophyane/task_compiler.py",
    }

    assert not (
        false_targets
        & {
            ref.path
            for ref in refs
        }
    )

    # Sophyane itself does not currently expose the user's requested
    # application middleware surface, so this task must remain unresolved.
    assert result.handled
    assert not result.ok
    assert result.unresolved
    assert result.execution_plan == []
