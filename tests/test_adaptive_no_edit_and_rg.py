from sophyane.adaptive_execution import (
    _explicit_no_edit_request,
    _is_read_only_inspection_command,
)


def test_do_not_create_new_files_does_not_forbid_editing_existing_files():
    request = (
        "Modify the existing source file only. "
        "Do not create new files."
    )

    assert _explicit_no_edit_request(request) is False


def test_explicit_do_not_modify_remains_no_edit():
    assert (
        _explicit_no_edit_request(
            "Inspect the repository but do not modify existing files."
        )
        is True
    )


def test_read_only_request_remains_no_edit():
    assert (
        _explicit_no_edit_request(
            "This is a read-only repository inspection."
        )
        is True
    )


def test_rg_is_read_only_inspection():
    assert (
        _is_read_only_inspection_command(
            "rg -n targeted_patch src tests"
        )
        is True
    )


def test_absolute_rg_is_read_only_inspection():
    assert (
        _is_read_only_inspection_command(
            "/data/data/com.termux/files/usr/bin/rg -n foo src"
        )
        is True
    )


def test_do_not_create_or_modify_is_no_edit():
    assert (
        _explicit_no_edit_request(
            "Do not create or modify files."
        )
        is True
    )


def test_do_not_create_or_edit_is_no_edit():
    assert (
        _explicit_no_edit_request(
            "Do not create or edit files."
        )
        is True
    )


def test_do_not_create_or_write_is_no_edit():
    assert (
        _explicit_no_edit_request(
            "Do not create or write files."
        )
        is True
    )


# SOPHYANE_SCOPED_NO_EDIT_RSI_RED_V1

def test_descriptive_read_only_phrase_does_not_cancel_explicit_source_authorization():
    request = (
        "Sophyane RSI critical repair. "
        "Source edits are explicitly authorized. "
        "Repair the defect that was incorrectly treated as read-only."
    )

    assert _explicit_no_edit_request(request) is False


def test_specific_artifact_protection_does_not_cancel_other_authorized_source_edits():
    request = (
        "Sophyane RSI critical repair. "
        "Source edits are explicitly authorized. "
        "Repair src/sophyane/adaptive_execution.py. "
        "Do not create or modify "
        "mode6_ladder_workspace/natural_request.txt."
    )

    assert _explicit_no_edit_request(request) is False


def test_global_file_prohibition_still_wins_over_conflicting_authorization():
    request = (
        "Source edits are explicitly authorized. "
        "Do not edit any files."
    )

    assert _explicit_no_edit_request(request) is True


# SOPHYANE_SINGLE_NO_EDIT_DEFINITION_RED_V1

def test_no_edit_parser_has_one_authoritative_definition():
    import ast
    from pathlib import Path

    path = Path("src/sophyane/adaptive_execution.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_explicit_no_edit_request"
    ]

    assert len(definitions) == 1, (
        "_explicit_no_edit_request must have exactly one "
        f"authoritative definition, found {len(definitions)}"
    )

    assert definitions[0].lineno < 200


def test_shell_builtin_command_is_accepted_for_read_only_inspection():
    from pathlib import Path
    from sophyane.adaptive_execution import _command_problem

    problem = _command_problem(
        {"type": "command", "command": "command -v rg"},
        Path(".").resolve(),
    )

    assert problem == ""
