from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    compile_task,
)

from sophyane.task_executor import (
    execute_compiled_task,
    executor_catalog,
)


PROMPT = (
    "Implement protection against cache stampede around a "
    "database-backed product lookup using single-flight locking, "
    "bounded stale serving, and safe fallback behavior."
)


def _write(
    root: Path,
    *,
    with_singleflight: bool = True,
):
    path = (
        root
        / "app"
        / "products.py"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    singleflight = (
        "    singleflight,\n"
        if with_singleflight
        else ""
    )

    path.write_text(
        (
            "def get_product(\n"
            "    cache,\n"
            "    database,\n"
            + singleflight
            + "    product_id,\n"
            "):\n"
            "    cached = cache.get(product_id)\n"
            "    if cached is not None:\n"
            "        return cached\n"
            "    product = database.get_product(product_id)\n"
            "    cache.set(product_id, product)\n"
            "    return product\n"
        ),
        encoding="utf-8",
    )

    return path


def test_c2_executor_authority_boundary():
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



def test_raw_cache_prompt_mutates(
    tmp_path: Path,
):
    path = _write(
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
    assert result.steps[0].mutated

    text = path.read_text()

    assert "SOPHYANE_CACHE_STAMPEDE_V1" in text
    assert "singleflight.lock" in text
    assert "cache.get_stale" in text
    assert "database.get_product" in text
    assert "cache.set" in text

    compile(
        text,
        str(path),
        "exec",
    )


def test_cache_executor_idempotent(
    tmp_path: Path,
):
    path = _write(
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

    second = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    after = path.read_bytes()

    assert second.ok
    assert not second.steps[0].mutated
    assert before == after


def test_cache_executor_fails_closed_without_singleflight(
    tmp_path: Path,
):
    path = _write(
        tmp_path,
        with_singleflight=False,
    )

    before = path.read_bytes()

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.ok

    result = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert not result.ok
    assert not result.steps[0].mutated
    assert path.read_bytes() == before


def test_cache_behavior(
    tmp_path: Path,
):
    path = _write(
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

    namespace = {}

    exec(
        path.read_text(),
        namespace,
    )

    get_product = namespace[
        "get_product"
    ]

    class Cache:
        def __init__(self):
            self.values = {}
            self.stale = {}

        def get(
            self,
            key,
        ):
            return self.values.get(
                key
            )

        def get_stale(
            self,
            key,
        ):
            return self.stale.get(
                key
            )

        def set(
            self,
            key,
            value,
        ):
            self.values[key] = value

    class Database:
        def __init__(self):
            self.calls = 0
            self.fail = False

        def get_product(
            self,
            key,
        ):
            self.calls += 1

            if self.fail:
                raise RuntimeError(
                    "db failure"
                )

            return {
                "id": key,
                "version": self.calls,
            }

    class Lock:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type,
            exc,
            tb,
        ):
            return False

    class SingleFlight:
        def __init__(self):
            self.keys = []

        def lock(
            self,
            key,
        ):
            self.keys.append(
                key
            )
            return Lock()

    cache = Cache()
    database = Database()
    singleflight = SingleFlight()

    first = get_product(
        cache,
        database,
        singleflight,
        "p1",
    )

    second = get_product(
        cache,
        database,
        singleflight,
        "p1",
    )

    assert first == second
    assert database.calls == 1
    assert singleflight.keys == [
        "p1",
    ]

    cache.values.clear()
    cache.stale["p2"] = {
        "id": "p2",
        "stale": True,
    }

    database.fail = True

    stale = get_product(
        cache,
        database,
        singleflight,
        "p2",
    )

    assert stale == {
        "id": "p2",
        "stale": True,
    }
