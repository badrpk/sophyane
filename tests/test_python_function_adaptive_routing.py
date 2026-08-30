from __future__ import annotations

import re
from pathlib import Path

import sophyane.local_coding_capability as coding


def _match(
    filename: str,
):
    match = re.match(
        r"(?P<filename>.+)",
        filename,
    )

    assert match is not None

    return match


def test_explicit_function_contract_uses_adaptive_route(
    tmp_path: Path,
    monkeypatch,
):
    calls = []

    sentinel = coding.CodingResult(
        handled=True,
        ok=False,
        capability="test.adaptive",
        summary="adaptive sentinel",
        workspace=str(tmp_path),
        files=[],
        evidence=[],
        error="sentinel",
    )

    def fake_adaptive(
        *args,
        **kwargs,
    ):
        calls.append(
            (
                args,
                kwargs,
            )
        )

        return sentinel

    monkeypatch.setattr(
        coding,
        "_python_adaptive_tdd_action",
        fake_adaptive,
    )

    def forbidden_default(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "_default_python must not own "
            "an explicit function contract"
        )

    monkeypatch.setattr(
        coding,
        "_default_python",
        forbidden_default,
    )

    result = coding._python_action(
        (
            "Create solution.py. "
            "Define function "
            "normalize_records(records)."
        ),
        _match(
            "solution.py"
        ),
        tmp_path,
    )

    assert result is sentinel
    assert len(calls) == 1


def test_generic_python_request_preserves_default_route(
    tmp_path: Path,
    monkeypatch,
):
    adaptive_called = False

    def forbidden_adaptive(
        *args,
        **kwargs,
    ):
        nonlocal adaptive_called

        adaptive_called = True

        raise AssertionError(
            "generic request must not be "
            "forced into explicit-function routing"
        )

    monkeypatch.setattr(
        coding,
        "_python_adaptive_tdd_action",
        forbidden_adaptive,
    )

    result = coding._python_action(
        (
            "Create hello.py that prints "
            "'hello'."
        ),
        _match(
            "hello.py"
        ),
        tmp_path,
    )

    assert result.handled is True
    assert result.ok is True
    assert adaptive_called is False

    target = (
        tmp_path
        / "hello.py"
    )

    assert target.is_file()

    assert (
        "hello"
        in target.read_text(
            encoding="utf-8",
        )
    )
