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
