from __future__ import annotations

from sophyane.v13_cli import (
    _semantic_generation_budget,
)


def test_planner_uses_256_budget():
    result = _semantic_generation_budget(
        '{"instruction":"choose action"}',
        "strict execution planner",
    )

    assert result == 256


def test_planner_reset_uses_256_budget():
    result = _semantic_generation_budget(
        '{"planner_reset":true}',
        "strict execution planner",
    )

    assert result == 256


def test_compact_adaptive_repair_uses_320_budget():
    result = _semantic_generation_budget(
        (
            "ADAPTIVE EXECUTION REPAIR FOR THE CURRENT TASK. "
            "Return exactly one compact run_command action."
        ),
        "execution worker",
    )

    assert result == 320


def test_file_bearing_adaptive_repair_keeps_normal_budget():
    result = _semantic_generation_budget(
        (
            "ADAPTIVE EXECUTION REPAIR FOR THE CURRENT TASK. "
            "Return one write_file action with complete content. "
            "Keep file content in each response below 2600 characters. "
            "For a large file, first use write_file with the first chunk, "
            "then append_file for later chunks."
        ),
        "execution worker",
    )

    assert result is None


def test_generic_artifact_compact_json_keeps_normal_budget():
    result = _semantic_generation_budget(
        (
            '{"mode":"generic_artifact_generation",'
            '"instruction":"generate complete files"}'
        ),
        "strict execution planner",
    )

    assert result is None


def test_generic_artifact_pretty_json_keeps_normal_budget():
    result = _semantic_generation_budget(
        (
            '{ "mode" : "generic_artifact_generation", '
            '"instruction" : "generate complete files" }'
        ),
        "strict execution planner",
    )

    assert result is None


def test_generic_artifact_single_quote_form_keeps_normal_budget():
    result = _semantic_generation_budget(
        (
            "{'mode':'generic_artifact_generation',"
            "'instruction':'generate complete files'}"
        ),
        "strict execution planner",
    )

    assert result is None


def test_unrelated_mode_preserves_planner_budget():
    result = _semantic_generation_budget(
        (
            '{"mode":"planner",'
            '"instruction":"choose action"}'
        ),
        "strict execution planner",
    )

    assert result == 256


def test_ordinary_generation_has_no_semantic_ceiling():
    result = _semantic_generation_budget(
        "Write a complete Python application.",
        "general assistant",
    )

    assert result is None
