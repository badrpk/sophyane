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
        lambda _prompt, **_kwargs: next(
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


def test_adaptive_validator_rejects_unimported_pytest() -> None:
    import pytest

    from sophyane.local_coding_capability import (
        _validate_generated_python,
    )

    with pytest.raises(
        ValueError,
        match="without importing pytest",
    ):
        _validate_generated_python(
            (
                "from probe import value\n"
                "\n"
                "def test_value():\n"
                "    assert value() == 1\n"
                "\n"
                "def test_error():\n"
                "    with pytest.raises(ValueError):\n"
                "        value()\n"
            ),
            function_name="value",
            is_test=True,
            module_name="probe",
        )


def test_adaptive_validator_accepts_imported_pytest() -> None:
    from sophyane.local_coding_capability import (
        _validate_generated_python,
    )

    _validate_generated_python(
        (
            "import pytest\n"
            "from probe import value\n"
            "\n"
            "def test_value():\n"
            "    assert value() == 1\n"
            "\n"
            "def test_error():\n"
            "    with pytest.raises(ValueError):\n"
            "        value()\n"
        ),
        function_name="value",
        is_test=True,
        module_name="probe",
    )


def test_median_contract_rejects_non_discriminating_mean_examples():
    import pytest
    import sophyane.local_coding_capability as coding

    tests = """
from transfer_probe import midpoint_stat

def test_odd():
    assert midpoint_stat([1, 3, 5]) == 3

def test_even():
    assert midpoint_stat([1, 2, 3, 4]) == 2.5
"""

    with pytest.raises(
        ValueError,
        match="non-discriminating",
    ):
        coding._validate_generated_test_contract(
            request=(
                "Create midpoint_stat(values) that calculates "
                "the median for odd and even numeric lists."
            ),
            function_name="midpoint_stat",
            test_source=tests,
        )


def test_median_contract_accepts_mean_discriminating_example():
    import sophyane.local_coding_capability as coding

    tests = """
from transfer_probe import midpoint_stat

def test_unsorted_odd():
    assert midpoint_stat([100, 1, 2]) == 2

def test_even():
    assert midpoint_stat([1, 4, 5, 100]) == 4.5
"""

    coding._validate_generated_test_contract(
        request=(
            "Create midpoint_stat(values) that calculates "
            "the median for odd and even numeric lists."
        ),
        function_name="midpoint_stat",
        test_source=tests,
    )


def test_adaptive_tdd_retries_outer_red_round_after_generation_rejection(
    tmp_path,
    monkeypatch,
):
    import sophyane.local_coding_capability as coding

    calls = []

    real_generation = coding._adaptive_generation

    def generation(**kwargs):
        calls.append(
            {
                "round": kwargs.get("generation_round"),
                "feedback": kwargs.get("execution_feedback", ""),
            }
        )

        if len(calls) == 1:
            raise ValueError(
                "Generated pytest is non-discriminating"
            )

        return real_generation(**kwargs)

    monkeypatch.setattr(
        coding,
        "_adaptive_generation",
        generation,
    )

    responses = iter(
        [
            # RED candidate generated by real _adaptive_generation on
            # outer round 2.
            """{
              "broken_source":
                "def midpoint_stat(values):\\n    return sum(values) / len(values)\\n",
              "test_source":
                "from retry_probe import midpoint_stat\\n\\ndef test_odd():\\n    assert midpoint_stat([100, 1, 2]) == 2\\n\\ndef test_even():\\n    assert midpoint_stat([1, 4, 5, 100]) == 4.5\\n"
            }""",
            # Repair.
            """{
              "diagnosis": "Implementation computes mean instead of median.",
              "source":
                "def midpoint_stat(values):\\n    values = sorted(values)\\n    n = len(values)\\n    if n % 2:\\n        return values[n // 2]\\n    return (values[n // 2 - 1] + values[n // 2]) / 2\\n"
            }""",
        ]
    )

    monkeypatch.setattr(
        coding,
        "_ask_local_coding_model",
        lambda _prompt, **_kwargs: next(responses),
    )

    result = coding.try_coding_request(
        (
            "Create retry_probe.py with midpoint_stat(values) and use pytest "
            "RED-GREEN repair until all tests pass. The function must calculate "
            "the median for odd and even numeric lists."
        ),
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert len(calls) >= 2
    assert calls[0]["round"] == 0
    assert calls[1]["round"] == 1
    assert "non-discriminating" in calls[1]["feedback"]


def test_red_defect_guidance_wrapper_uses_selected_contract() -> None:
    from sophyane.local_coding_capability import (
        _format_red_defect_guidance,
    )

    request = (
        "Create descending_lock.py with descending_values(values). "
        "Sort the numeric list in descending order."
    )

    guidance = _format_red_defect_guidance(
        request=request,
    )

    lowered = guidance.lower()

    assert "plausible deliberate red defect" in lowered
    assert "ascending order" in lowered
    assert "descending-sort" in lowered


def test_red_generation_prompt_contains_contract_directed_guidance(
    monkeypatch,
) -> None:
    import sophyane.local_coding_capability as capability

    request = (
        "Create descending_lock.py with descending_values(values) and use "
        "pytest RED-GREEN repair until all tests pass. Sort the numeric list "
        "in descending order and preserve duplicates."
    )

    captured_prompts: list[str] = []

    def fake_model_call(
        prompt,
        **_kwargs,
    ):
        captured_prompts.append(
            str(prompt)
        )

        return """
{
  "broken_source": "def descending_values(values):\\n    return sorted(values)\\n",
  "test_source": "from descending_lock import descending_values\\n\\ndef test_descending():\\n    assert descending_values([1, 9, 2, 5]) == [9, 5, 2, 1]\\n"
}
"""

    monkeypatch.setattr(
        capability,
        "_ask_local_coding_model",
        fake_model_call,
    )

    broken_source, test_source = (
        capability._adaptive_generation(
            request=request,
            filename="descending_lock.py",
            function_name="descending_values",
            parameters=[
                "values",
            ],
            execution_feedback="",
            memory_context=None,
            generation_round=0,
        )
    )

    assert captured_prompts

    prompt = captured_prompts[0].lower()

    assert (
        "contract-directed red defect guidance"
        in prompt
    )

    assert (
        "sort the values in ascending order instead"
        in prompt
    )

    assert (
        "plausible deliberate red defect"
        in prompt
    )

    # The selected contract owns the objective tests, so generated
    # model tests are replaced by the descending-sort contract.
    assert (
        "return sorted(values)"
        in broken_source
    )

    assert (
        "test_objective_descending_unsorted"
        in test_source
    )

    assert (
        "descending_values([1, 9, 2, 5]) == [9, 5, 2, 1]"
        in test_source
    )


def test_contract_guided_round_zero_candidate_is_discriminating(
    tmp_path,
) -> None:
    """
    Lock the objective property demonstrated by the live probe:

    the descending contract's recommended deliberate defect is ascending
    ordering, and the harness-owned objective tests reject that defect.
    """
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
        objective_preflight_test_source,
    )

    request = (
        "Create descending_lock.py with descending_values(values). "
        "Sort the numeric list in descending order and preserve duplicates."
    )

    guidance = format_red_defect_guidance(
        request=request,
    )

    assert "ascending order" in guidance.lower()

    source = (
        "def descending_values(values):\n"
        "    return sorted(values)\n"
    )

    tests = objective_preflight_test_source(
        request=request,
        module_name="descending_lock",
        function_name="descending_values",
    )

    assert tests is not None

    source_path = (
        tmp_path
        / "descending_lock.py"
    )

    test_path = (
        tmp_path
        / "test_descending_lock.py"
    )

    source_path.write_text(
        source,
        encoding="utf-8",
    )

    test_path.write_text(
        tests,
        encoding="utf-8",
    )

    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            test_path.name,
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    output = (
        completed.stdout
        + "\n"
        + completed.stderr
    )

    assert completed.returncode != 0
    assert (
        "test_objective_descending_unsorted"
        in output
    )
    assert (
        "test_objective_descending_duplicates"
        in output
    )


def test_contract_guided_defect_and_green_repair_are_distinct(
    tmp_path,
) -> None:
    """
    Verify the deterministic RED -> GREEN witness independently of Qwen.
    """
    from sophyane.coding_contracts import (
        objective_preflight_test_source,
    )

    request = (
        "Create descending_lock.py with descending_values(values). "
        "Sort the numeric list in descending order and preserve duplicates."
    )

    tests = objective_preflight_test_source(
        request=request,
        module_name="descending_lock",
        function_name="descending_values",
    )

    assert tests is not None

    source_path = (
        tmp_path
        / "descending_lock.py"
    )

    test_path = (
        tmp_path
        / "test_descending_lock.py"
    )

    test_path.write_text(
        tests,
        encoding="utf-8",
    )

    source_path.write_text(
        (
            "def descending_values(values):\n"
            "    return sorted(values)\n"
        ),
        encoding="utf-8",
    )

    import subprocess
    import sys

    red = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            test_path.name,
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert red.returncode != 0

    source_path.write_text(
        (
            "def descending_values(values):\n"
            "    return sorted(values, reverse=True)\n"
        ),
        encoding="utf-8",
    )

    pycache = (
        tmp_path
        / "__pycache__"
    )

    if pycache.exists():
        import shutil

        shutil.rmtree(
            pycache
        )

    green = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            test_path.name,
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert green.returncode == 0, (
        green.stdout
        + "\n"
        + green.stderr
    )
