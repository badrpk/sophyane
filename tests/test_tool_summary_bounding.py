from __future__ import annotations

from sophyane.agent import (
    _bounded_tool_context,
)


def test_small_tool_output_is_unchanged():
    value = "hello"

    assert (
        _bounded_tool_context(
            value,
            limit=100,
        )
        == value
    )


def test_large_tool_output_is_bounded():
    value = (
        "A" * 100_000
    )

    result = _bounded_tool_context(
        value,
        limit=10_000,
    )

    assert len(result) < 11_000

    assert (
        "SOPHYANE TOOL OUTPUT TRUNCATED"
        in result
    )


def test_bounded_context_keeps_head_and_tail():
    value = (
        "HEAD"
        + "x" * 50_000
        + "TAIL"
    )

    result = _bounded_tool_context(
        value,
        limit=8_000,
    )

    assert result.startswith(
        "HEAD"
    )

    assert result.endswith(
        "TAIL"
    )
