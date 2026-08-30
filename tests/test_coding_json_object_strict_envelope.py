from __future__ import annotations

import json

import pytest

from sophyane.local_coding_capability import (
    _coding_json_object,
    _direct_source_response_payload,
)


def test_global_decoder_accepts_complete_json_object() -> None:
    payload = {
        "source": "def example():\n    return 1\n",
    }

    assert (
        _coding_json_object(
            json.dumps(
                payload
            )
        )
        == payload
    )


def test_global_decoder_accepts_explicit_json_fence() -> None:
    payload = {
        "source": "def example():\n    return 1\n",
    }

    response = (
        "```json\n"
        + json.dumps(
            payload
        )
        + "\n```"
    )

    assert (
        _coding_json_object(
            response
        )
        == payload
    )


def test_global_decoder_rejects_plain_python_dict_literal() -> None:
    source = """def build():
    value = {"a": 1, "b": 2}
    return value
"""

    with pytest.raises(
        ValueError,
        match="canonical JSON object",
    ):
        _coding_json_object(
            source
        )


def test_global_decoder_rejects_prose_wrapped_json() -> None:
    response = (
        'Here is the result: {"source": "pass"}'
    )

    with pytest.raises(
        ValueError,
        match="canonical JSON object",
    ):
        _coding_json_object(
            response
        )


def test_global_decoder_rejects_python_fence() -> None:
    response = """```python
def example():
    return {"ok": True}
```"""

    with pytest.raises(
        ValueError,
        match="canonical JSON object",
    ):
        _coding_json_object(
            response
        )


def test_direct_decoder_still_accepts_plain_python() -> None:
    source = """def example():
    return {"ok": True}
"""

    payload = (
        _direct_source_response_payload(
            source
        )
    )

    assert (
        payload["source"]
        == source.strip()
    )


def test_direct_decoder_still_accepts_fenced_python() -> None:
    source = """def example():
    return {"ok": True}
"""

    payload = (
        _direct_source_response_payload(
            "```python\n"
            + source
            + "```"
        )
    )

    assert (
        payload["source"]
        == source.strip()
    )
