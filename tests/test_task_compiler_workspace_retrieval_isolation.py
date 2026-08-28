from __future__ import annotations

from pathlib import Path

from sophyane.task_compiler import (
    compile_task,
)


PROMPT = (
    "Integrate a circuit breaker around the primary payment "
    "gateway HTTP client. Open after 5 consecutive 5xx errors "
    "or timeouts within a 30s window and fall back to the "
    "secondary processor."
)


def _line(
    hit,
) -> str:
    return str(
        hit.get(
            "line",
            "",
        )
    )


def _source_path(
    hit,
) -> Path | None:
    line = _line(
        hit
    )

    if not line.startswith("/"):
        return None

    return Path(
        line.split(
            ":",
            1,
        )[0]
    ).resolve()


def _assert_inside(
    result,
    root: Path,
):
    root = root.resolve()

    for hit in result.repository_hits:
        source = _source_path(
            hit
        )

        if source is None:
            continue

        source.relative_to(
            root
        )


def test_retrieval_is_scoped_to_active_workspace(
    tmp_path: Path,
):
    app = (
        tmp_path
        / "app"
    )

    app.mkdir()

    (
        app
        / "payments.py"
    ).write_text(
        (
            "primary_gateway = object()\n"
            "secondary_processor = object()\n"
            "\n"
            "def charge(request):\n"
            "    try:\n"
            "        return primary_gateway.post(request)\n"
            "    except TimeoutError:\n"
            "        return secondary_processor.post(request)\n"
        ),
        encoding="utf-8",
    )

    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    _assert_inside(
        result,
        tmp_path,
    )


def test_empty_workspace_imports_no_external_hits(
    tmp_path: Path,
):
    (
        tmp_path
        / "README.txt"
    ).write_text(
        "isolated workspace\n",
        encoding="utf-8",
    )

    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    _assert_inside(
        result,
        tmp_path,
    )

    assert all(
        (
            source is None
            or str(
                source
            ).startswith(
                str(
                    tmp_path.resolve()
                )
            )
        )
        for source in (
            _source_path(
                hit
            )
            for hit
            in result.repository_hits
        )
    )


def test_sibling_repository_is_not_retrieved(
    tmp_path: Path,
):
    active = (
        tmp_path
        / "active"
    )

    sibling = (
        tmp_path
        / "sophyane"
    )

    active.mkdir()
    sibling.mkdir()

    (
        active
        / "README.txt"
    ).write_text(
        "active workspace\n",
        encoding="utf-8",
    )

    (
        sibling
        / "payments.py"
    ).write_text(
        (
            "primary_gateway = object()\n"
            "secondary_processor = object()\n"
            "circuit_breaker = True\n"
        ),
        encoding="utf-8",
    )

    result = compile_task(
        PROMPT,
        workspace=active,
    )

    _assert_inside(
        result,
        active,
    )

    for hit in result.repository_hits:
        assert (
            str(
                sibling.resolve()
            )
            not in _line(
                hit
            )
        )


def test_empty_workspace_still_fails_closed(
    tmp_path: Path,
):
    result = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert result.handled
    assert not result.ok
    assert result.unresolved
    assert result.execution_plan == []


def test_same_domain_payment_workspace_still_compiles(
    tmp_path: Path,
):
    app = (
        tmp_path
        / "app"
    )

    app.mkdir()

    (
        app
        / "payments.py"
    ).write_text(
        (
            "primary_gateway = object()\n"
            "secondary_processor = object()\n"
            "\n"
            "def charge(request):\n"
            "    try:\n"
            "        return primary_gateway.post(request)\n"
            "    except TimeoutError:\n"
            "        return secondary_processor.post(request)\n"
        ),
        encoding="utf-8",
    )

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

    assert (
        result.execution_plan[
            0
        ][
            "contract"
        ]
        == "circuit_breaker"
    )
