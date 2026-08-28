from __future__ import annotations

import importlib.util
from pathlib import Path

from sophyane.task_compiler import (
    compile_task,
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


def _supported(
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
def rate_limit_middleware(request, redis_client):
    client_ip = request.client.host
    redis_client.get("warmup:" + client_ip)
    return {
        "status": 200,
        "headers": {},
        "body": "ok",
    }
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return path


def _unsupported(
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
def rate_limit_middleware(request):
    client_ip = request.client.host
    return {
        "status": 200,
        "headers": {},
        "body": "ok",
    }
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return path


class User:
    def __init__(
        self,
        authenticated=False,
    ):
        self.is_authenticated = (
            authenticated
        )


class Client:
    def __init__(
        self,
        host,
    ):
        self.host = host


class Request:
    def __init__(
        self,
        host,
        authenticated=False,
    ):
        self.client = Client(
            host
        )

        self.user = User(
            authenticated
        )


class FakeRedis:
    def __init__(self):
        self.windows = {}

    def get(
        self,
        key,
    ):
        return None

    def eval(
        self,
        lua,
        number_of_keys,
        key,
        now_ms,
        window_ms,
        limit,
        member,
    ):
        assert number_of_keys == 1

        upper = lua.upper()

        assert "ZREMRANGEBYSCORE" in upper
        assert "ZCARD" in upper
        assert "ZADD" in upper
        assert "PEXPIRE" in upper
        assert "INCR" not in upper

        now_ms = int(
            now_ms
        )

        window_ms = int(
            window_ms
        )

        limit = int(
            limit
        )

        values = self.windows.setdefault(
            key,
            [],
        )

        cutoff = (
            now_ms
            - window_ms
        )

        values[:] = [
            value
            for value in values
            if value > cutoff
        ]

        if len(values) >= limit:
            oldest = min(
                values
            )

            return (
                0,
                len(values),
                oldest + window_ms,
            )

        values.append(
            now_ms
        )

        return (
            1,
            len(values),
            now_ms + window_ms,
        )


def _load(
    path: Path,
):
    spec = (
        importlib.util.spec_from_file_location(
            "v63_rate_limit",
            path,
        )
    )

    assert spec is not None
    assert spec.loader is not None

    module = (
        importlib.util.module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def test_v63_catalog_exact():
    assert set(
        executor_catalog()
    ) == {
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


def test_v63_raw_prompt_mutates(
    tmp_path: Path,
):
    path = _supported(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.ok
    assert compiled.unresolved == []

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok
    assert result.steps
    assert result.steps[0].mutated

    text = path.read_text(
        encoding="utf-8"
    )

    assert (
        "SOPHYANE_REDIS_SLIDING_WINDOW_RATE_LIMIT_V1"
        in text
    )

    assert "_sophyane_original_rate_limit_middleware" in text

    for token in (
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


def test_v63_repeat_execution_zero_bytes(
    tmp_path: Path,
):
    path = _supported(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    first = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert first.ok
    assert first.steps[0].mutated

    before = path.read_bytes()

    compiled_again = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    second = execute_compiled_task(
        compiled_again,
        workspace=tmp_path,
    )

    assert second.ok
    assert not second.steps[0].mutated

    assert path.read_bytes() == before


def test_v63_missing_redis_dependency_fails_closed(
    tmp_path: Path,
):
    path = _unsupported(
        tmp_path
    )

    before = path.read_bytes()

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    if not compiled.ok:
        assert path.read_bytes() == before
        return

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert not result.ok
    assert result.steps
    assert all(
        not step.mutated
        for step in result.steps
    )

    assert path.read_bytes() == before


def test_v63_100_requests_then_429(
    tmp_path: Path,
):
    path = _supported(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok

    module = _load(
        path
    )

    redis_client = FakeRedis()

    request = Request(
        "203.0.113.10"
    )

    for index in range(
        100
    ):
        response = (
            module.rate_limit_middleware(
                request,
                redis_client,
            )
        )

        assert response[
            "status"
        ] == 200

        assert response[
            "headers"
        ][
            "X-RateLimit-Limit"
        ] == "100"

        assert int(
            response[
                "headers"
            ][
                "X-RateLimit-Remaining"
            ]
        ) == (
            99 - index
        )

    limited = (
        module.rate_limit_middleware(
            request,
            redis_client,
        )
    )

    assert limited[
        "status"
    ] == 429

    assert limited[
        "status_code"
    ] == 429

    assert limited[
        "body"
    ] == "Too Many Requests"

    headers = limited[
        "headers"
    ]

    assert headers[
        "X-RateLimit-Limit"
    ] == "100"

    assert headers[
        "X-RateLimit-Remaining"
    ] == "0"

    assert int(
        headers[
            "X-RateLimit-Reset"
        ]
    ) > 0

    assert int(
        headers[
            "Retry-After"
        ]
    ) >= 1


def test_v63_authenticated_bypasses_limiter(
    tmp_path: Path,
):
    path = _supported(
        tmp_path
    )

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert result.ok

    module = _load(
        path
    )

    redis_client = FakeRedis()

    request = Request(
        "203.0.113.20",
        authenticated=True,
    )

    for _ in range(
        150
    ):
        response = (
            module.rate_limit_middleware(
                request,
                redis_client,
            )
        )

        assert response[
            "status"
        ] == 200

    # Original middleware may call Redis.get(), but the
    # sliding-window Lua state must remain completely unused.
    assert redis_client.windows == {}
