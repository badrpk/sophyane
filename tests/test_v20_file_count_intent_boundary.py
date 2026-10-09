import pytest

from sophyane.runtime_filesystem_capabilities_v20 import (
    classify_request,
)


@pytest.mark.parametrize(
    "user_text",
    [
        (
            "Audit repository files. Apply a security patch "
            "that checks source.count(anchor)."
        ),
        (
            "Review files and explain how Python "
            "list.count(value) works."
        ),
        (
            "Inspect files without changing them. "
            "The supplied code contains source.count(anchor)."
        ),
    ],
)
def test_incidental_count_does_not_select_file_count(
    user_text,
):
    assert classify_request(user_text) is None


@pytest.mark.parametrize(
    "user_text",
    [
        "Count files in the repository.",
        "How many files are in this project?",
        "Give me the number of files in this folder.",
    ],
)
def test_explicit_file_count_still_works(user_text):
    assert classify_request(user_text) == {
        "type": "filesystem.file_count"
    }
