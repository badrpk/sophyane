from __future__ import annotations

from sophyane.fast_local_coding import (
    _candidate_prompt,
    _repair_prompt,
)


def test_candidate_prompt_treats_request_as_literal_contract() -> None:
    prompt = _candidate_prompt(
        (
            "Implement work(values, size).\n"
            "- Convert size to int.\n"
            "- Accept any iterable.\n"
            "- Conversion errors must propagate.\n"
        ),
        "sample.py",
        (
            "def work(values, size):\n"
            "    raise NotImplementedError\n"
        ),
        (
            "def test_example():\n"
            "    assert work([1], 1) == [1]\n"
        ),
    )

    assert (
        "Every explicit USER REQUEST requirement is mandatory"
        in prompt
    )

    assert (
        "Do not replace a requested conversion with an isinstance restriction"
        in prompt
    )

    assert (
        "materialize it exactly once"
        in prompt
    )

    assert (
        "must propagate"
        in prompt
    )


def test_repair_prompt_maps_failure_back_to_request_clause() -> None:
    prompt = _repair_prompt(
        (
            "Implement divide(a, b).\n"
            "- Convert a and b to float.\n"
            "- Conversion errors must propagate.\n"
        ),
        "sample.py",
        (
            "def divide(a, b):\n"
            "    try:\n"
            "        return float(a) / float(b)\n"
            "    except ValueError:\n"
            "        return None\n"
        ),
        (
            "FAILED test_bad_conversion - "
            "Failed: DID NOT RAISE ValueError"
        ),
    )

    assert (
        "Identify which explicit USER REQUEST clause governs that behavior"
        in prompt
    )

    assert (
        "If errors are required to propagate"
        in prompt
    )

    assert (
        "do not catch and convert them to"
        in prompt
    )


def test_repair_prompt_forbids_recursive_overreach() -> None:
    prompt = _repair_prompt(
        (
            "Implement flatten_once(values).\n"
            "- Flatten exactly one nesting level.\n"
        ),
        "flatten.py",
        (
            "def flatten_once(values):\n"
            "    return []\n"
        ),
        (
            "assert [1, 2] == [[1], 2]"
        ),
    )

    assert (
        "If behavior is explicitly limited to one level, do not recurse"
        in prompt
    )


def test_repair_prompt_preserves_no_test_special_casing() -> None:
    prompt = _repair_prompt(
        "Fix f(x).",
        "sample.py",
        "def f(x):\n    return x\n",
        "FAILED test_x",
    )

    assert (
        "Do not special-case test names"
        in prompt
    )
