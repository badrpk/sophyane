import pytest

from sophyane.adaptive_execution import (
    _read_only_execution_obligations,
)


@pytest.mark.parametrize(
    ("task_text", "expected"),
    [
        (
            "Inspect the repository. Do not run tests.",
            set(),
        ),
        (
            "Inspect the repository. Do not edit files, "
            "install packages, run tests, or commit changes.",
            set(),
        ),
        (
            "Inspect the repository without running tests.",
            set(),
        ),
        (
            "Inspect the repository; never execute pytest.",
            set(),
        ),
        (
            "Run all 15 tests and demonstrate the CLI.",
            {"tests", "cli"},
        ),
        (
            "Run the existing tests without modifying files.",
            {"tests"},
        ),
        (
            "Do not run tests. Inspect the repository.",
            set(),
        ),
        (
            "Do not run tests. Then run the CLI.",
            {"cli"},
        ),
        (
            "Do not run tests. Later, run all 15 tests.",
            {"tests"},
        ),
    ],
)
def test_negated_test_mentions_do_not_create_obligations(
    task_text,
    expected,
):
    assert _read_only_execution_obligations(task_text) == expected
