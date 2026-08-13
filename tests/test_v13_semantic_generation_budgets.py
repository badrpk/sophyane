from __future__ import annotations

from pathlib import Path

from sophyane.v13_cli import (
    _semantic_generation_budget,
)


def test_planner_budget_remains_256():
    assert (
        _semantic_generation_budget(
            '{"instruction":"choose action"}',
            "strict execution planner",
        )
        == 256
    )


def test_adaptive_execution_repair_budget_is_320():
    assert (
        _semantic_generation_budget(
            (
                "ADAPTIVE EXECUTION REPAIR FOR THE CURRENT TASK. "
                "Return one compact run_command action."
            ),
            "execution worker",
        )
        == 320
    )


def test_adaptive_artifact_generation_keeps_normal_budget():
    assert (
        _semantic_generation_budget(
            (
                "ADAPTIVE EXECUTION REPAIR FOR THE CURRENT TASK. "
                "Return a write_file action with complete content. "
                "Keep file content in each response below 2600 characters. "
                "For a large file, first use write_file with the first chunk, "
                "then append_file for later chunks."
            ),
            "execution worker",
        )
        is None
    )


def test_generic_artifact_generation_keeps_normal_budget():
    assert (
        _semantic_generation_budget(
            (
                '{"mode":"generic_artifact_generation",'
                '"instruction":"generate complete files"}'
            ),
            "strict execution planner",
        )
        is None
    )


def test_ordinary_artifact_generation_has_no_global_320_cap():
    assert (
        _semantic_generation_budget(
            "Generate a complete Python application.",
            "general coding assistant",
        )
        is None
    )


def test_backend_uses_semantic_policy():
    source = Path(
        "src/sophyane/v13_cli.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        source.count(
            "def _semantic_generation_budget("
        )
        == 1
    )

    assert (
        source.count(
            "semantic_budget = _semantic_generation_budget("
        )
        == 1
    )

    assert (
        "generate_with_budget"
        in source
    )

    assert (
        "max_tokens=semantic_budget"
        in source
    )
