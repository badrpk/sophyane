from pathlib import Path

from sophyane.capability_executors import (
    execute_deterministic_capability,
)


def test_exact_verified_write_bypasses_folder_classifier(
    tmp_path: Path,
) -> None:
    result = execute_deterministic_capability(
        "Using filesystem tools, create harness_verify.txt in the current "
        "workspace containing exactly HARNESS_OK with no newline. Read the "
        "file back, verify it byte-for-byte, and respond only VERIFIED.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "filesystem.write_exact_verified"
    assert result.text == "VERIFIED"
    assert (tmp_path / "harness_verify.txt").read_bytes() == b"HARNESS_OK"
    assert result.data["byte_for_byte_verified"] is True
    assert result.data["newline_added"] is False


def test_ordinary_folder_listing_is_unchanged(
    tmp_path: Path,
) -> None:
    (tmp_path / "alpha").mkdir()

    result = execute_deterministic_capability(
        "List the folders in the current workspace.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.capability_id == "filesystem.list_folders"
    assert result.data["folders"] == ["alpha"]


def test_non_exact_general_file_request_falls_through(
    tmp_path: Path,
) -> None:
    result = execute_deterministic_capability(
        "Create a detailed report file about the project.",
        workspace=tmp_path,
    )

    assert result is None
