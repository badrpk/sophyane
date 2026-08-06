from __future__ import annotations

import json
from pathlib import Path

from sophyane.evolution.validators import (
    _artifact_workspace,
    _python,
)
from sophyane.local_coding_capability import (
    try_coding_request,
)


def test_python_capability_creates_requested_add_and_pytest(
    tmp_path: Path,
) -> None:
    result = try_coding_request(
        (
            "Create calc.py with add(a, b). "
            "Create and run a pytest test proving "
            "add(20, 22) equals 42."
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability == (
        "development.python_create_validate_pytest"
    )
    assert result.files == [
        "calc.py",
        "test_calc.py",
    ]

    source = (
        tmp_path
        / "calc.py"
    ).read_text(
        encoding="utf-8"
    )

    tests = (
        tmp_path
        / "test_calc.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "def add(a:" in source
    assert "return a + b" in source
    assert "assert add(20, 22) == 42" in tests
    assert result.evidence[-1].exit_code == 0


def test_python_capability_creates_requested_multiply(
    tmp_path: Path,
) -> None:
    result = try_coding_request(
        (
            "Create math_probe.py with multiply(a, b), "
            "create a pytest proving multiply(6, 7) "
            "equals 42, and run the test."
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True

    source = (
        tmp_path
        / "math_probe.py"
    ).read_text(
        encoding="utf-8"
    )

    tests = (
        tmp_path
        / "test_math_probe.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "def multiply(a:" in source
    assert "return a * b" in source
    assert (
        "assert multiply(6, 7) == 42"
        in tests
    )


def test_python_validator_uses_nested_harness_workspace(
    tmp_path: Path,
) -> None:
    artifact = (
        tmp_path
        / ".sophyane-workspace"
    )
    artifact.mkdir()

    (
        artifact
        / "calc.py"
    ).write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    (
        artifact
        / "test_calc.py"
    ).write_text(
        "from calc import add\n"
        "\n"
        "def test_add():\n"
        "    assert add(20, 22) == 42\n",
        encoding="utf-8",
    )

    report = {
        "workspace": str(
            artifact
        )
    }

    (
        artifact
        / ".sophyane-harness-report.json"
    ).write_text(
        json.dumps(
            report
        ),
        encoding="utf-8",
    )

    assert (
        _artifact_workspace(
            tmp_path
        )
        == artifact.resolve()
    )

    checks, errors = _python(
        tmp_path
    )

    assert checks == {
        "python_file_exists": True,
        "syntax_valid": True,
        "pytest_passed": True,
    }
    assert errors == []


def test_adaptive_tdd_qwen_worker_red_green(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json

    import sophyane.local_coding_capability as coding

    responses = iter(
        [
            json.dumps(
                {
                    "broken_source": (
                        "def mean(values):\n"
                        "    return sum(values)\n"
                    ),
                    "test_source": (
                        "from stats import mean\n"
                        "\n"
                        "def test_mean_typical():\n"
                        "    assert mean([2, 4, 6]) == 4\n"
                        "\n"
                        "def test_mean_single():\n"
                        "    assert mean([9]) == 9\n"
                    ),
                }
            ),
            json.dumps(
                {
                    "diagnosis": (
                        "The implementation returns the sum "
                        "instead of the arithmetic mean."
                    ),
                    "source": (
                        "def mean(values):\n"
                        "    return sum(values) / len(values)\n"
                    ),
                }
            ),
        ]
    )

    monkeypatch.setattr(
        coding,
        "_ask_local_coding_model",
        lambda _prompt: next(
            responses
        ),
    )

    result = coding.try_coding_request(
        (
            "Create stats.py with mean(values), intentionally introduce "
            "a defect, create meaningful pytest tests including an edge "
            "case, run them, diagnose the failure from test evidence, "
            "repair the implementation without changing the tests, "
            "rerun pytest, and only report success when all tests pass."
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result.handled is True
    assert result.ok is True

    assert result.capability == (
        "development."
        "python_adaptive_pytest_red_green"
    )

    assert [
        item.exit_code
        for item in result.evidence
    ] == [
        1,
        0,
    ]


def test_adaptive_source_field_normalizes_weak_model_lists() -> None:
    from sophyane.local_coding_capability import (
        _adaptive_source_field,
    )

    payload = {
        "test_source": [
            {
                "test_code": (
                    "def test_one():\n"
                    "    assert True\n"
                ),
            },
            {
                "test_code": (
                    "def test_two():\n"
                    "    assert True\n"
                ),
            },
        ],
    }

    source = _adaptive_source_field(
        payload,
        "test_source",
    )

    assert "def test_one" in source
    assert "def test_two" in source


def test_sli_only_prefers_local_kernel_before_acquisition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.tui_v2 as tui
    import sophyane.sli_chunk_router as router
    import sophyane.unified_execution_kernel as kernel

    prompt = (
        "Create stats.py with mean(values), intentionally introduce "
        "a defect, create pytest tests, diagnose the failure, repair "
        "it, rerun pytest, and only report success when tests pass."
    )

    calls: list[str] = []

    def fake_kernel(
        message,
        *,
        workspace=None,
    ):
        calls.append(
            "kernel"
        )

        assert message == prompt
        assert workspace == tmp_path

        return (
            "LOCAL_KERNEL_HANDLED"
        )

    def forbidden_sli(
        *_args,
        **_kwargs,
    ):
        calls.append(
            "sli"
        )

        raise AssertionError(
            "SLI must not steal a locally handled coding request"
        )

    monkeypatch.chdir(
        tmp_path
    )

    monkeypatch.setenv(
        "SOPHYANE_SLI_ONLY",
        "1",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_chunks",
    )

    monkeypatch.setattr(
        kernel,
        "execute_text",
        fake_kernel,
    )

    monkeypatch.setattr(
        router,
        "try_sli_chunks",
        forbidden_sli,
    )

    result = tui._simple_chat_reply(
        prompt
    )

    assert result == (
        "LOCAL_KERNEL_HANDLED"
    )

    assert calls == [
        "kernel"
    ]
