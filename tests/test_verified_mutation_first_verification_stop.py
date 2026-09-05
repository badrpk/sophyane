from pathlib import Path


SOURCE = Path(
    "src/sophyane/adaptive_execution.py"
)


def test_verified_mutation_completion_marker_exists():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        source.count(
            "SOPHYANE_VERIFIED_MUTATION_COMPLETION_STOP_V1"
        )
        >= 2
    )

    assert (
        "workspace_mutated = False"
        in source
    )


def test_successful_file_actions_mark_workspace_mutated():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        'kind in {\n'
        '                "write_file",\n'
        '                "append_file",\n'
        '                "batch",'
        in source
    )

    assert (
        "workspace_mutated = True"
        in source
    )


def test_first_meaningful_verification_can_finish():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    marker = source.rindex(
        "SOPHYANE_VERIFIED_MUTATION_COMPLETION_STOP_V1"
    )

    section = source[
        marker:
        marker + 1800
    ]

    assert (
        "workspace_mutated"
        in section
    )

    assert (
        "not deterministic_verification_stage"
        in section
    )

    assert (
        "not bundle_first_full_stack"
        in section
    )

    assert (
        "Project implementation and verification completed "
        in section
    )

    assert (
        "return ("
        in section
    )


def test_duplicate_command_guard_is_preserved():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        "command_text in successful_commands"
        in source
    )

    assert (
        "SOPHYANE_DUPLICATE_COMMAND_COMPLETION_GATE_V1"
        in source
    )

    assert (
        "SOPHYANE_DUPLICATE_READ_ONLY_INSPECTION_V1"
        in source
    )

    assert (
        "not _is_read_only_inspection_command("
        in source
    )

    assert (
        "verification_result_is_meaningful("
        in source
    )

    assert (
        "Meaningful verification already passed earlier with "
        in source
    )

    assert (
        "Previously successful command was inspection/non-verifying"
        in source
    )


def test_full_stack_deterministic_verification_is_preserved():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        'deterministic_verification_stage = "prepare"'
        in source
    )

    assert (
        'verification_phase == "test"'
        in source
    )

    assert (
        "Service Fabric verification"
        in source
    )
