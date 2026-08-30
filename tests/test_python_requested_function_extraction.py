import pytest

from sophyane.local_coding_capability import (
    _requested_python_function,
)


@pytest.mark.parametrize(
    (
        "prompt_text",
        "expected",
    ),
    (
        (
            "Define function normalize_records(records).",
            (
                "normalize_records",
                [
                    "records",
                ],
            ),
        ),
        (
            "Create function add_values(a, b).",
            (
                "add_values",
                [
                    "a",
                    "b",
                ],
            ),
        ),
        (
            "Implement a function named parse_input(data).",
            (
                "parse_input",
                [
                    "data",
                ],
            ),
        ),
        (
            "Write function ping().",
            (
                "ping",
                [],
            ),
        ),
        (
            "Create module.py with parse_record(record)",
            (
                "parse_record",
                [
                    "record",
                ],
            ),
        ),
        (
            "Define function typed(value: str, limit: int = 2).",
            (
                "typed",
                [
                    "value",
                    "limit",
                ],
            ),
        ),
    ),
)
def test_requested_python_function_explicit_forms(
    prompt_text,
    expected,
):
    assert (
        _requested_python_function(
            prompt_text
        )
        == expected
    )


def test_requested_python_function_does_not_invent_contract():
    assert (
        _requested_python_function(
            "Create a Python file that prints hello."
        )
        is None
    )
