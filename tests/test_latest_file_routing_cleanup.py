from __future__ import annotations

from sophyane import tui_v2


def test_latest_file_request_with_machine_scope_is_detected() -> None:
    assert tui_v2._is_latest_file_inspection_request(
        "Which file on my computer was modified most recently?"
    )


def test_latest_file_request_without_machine_scope_is_detected() -> None:
    assert tui_v2._is_latest_file_inspection_request(
        "Show me the newest file."
    )


def test_last_amendment_wording_is_detected() -> None:
    assert tui_v2._is_latest_file_inspection_request(
        "Which file had the last amendment?"
    )


def test_unrelated_latest_request_is_not_filesystem_inspection() -> None:
    assert not tui_v2._is_latest_file_inspection_request(
        "What is the latest FastAPI version?"
    )


def test_generic_file_request_is_not_latest_file_inspection() -> None:
    assert not tui_v2._is_latest_file_inspection_request(
        "Create a file named notes.txt."
    )
