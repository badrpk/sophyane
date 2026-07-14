from __future__ import annotations

import json

import pytest

from sophyane.structured_output import (
    StructuredOutputError,
    parse_json_response,
    render_strict_json,
    requests_strict_json,
)


def test_parse_json_from_plain_and_fenced_output() -> None:
    assert parse_json_response('{"ok":true}') == {"ok": True}
    assert parse_json_response('Result:\n```json\n{"value":30}\n```') == {"value": 30}


def test_explicit_contract_fallback_is_compact_json() -> None:
    prompt = '''Execute a deterministic workflow.
Return ONLY strict JSON:
{"value":30,"trace":["load","transform","validate"],"valid":true}
'''
    output = render_strict_json(prompt, "The answer is thirty.")
    assert json.loads(output) == {
        "value": 30,
        "trace": ["load", "transform", "validate"],
        "valid": True,
    }


def test_invalid_provider_output_without_contract_fails() -> None:
    with pytest.raises(StructuredOutputError):
        render_strict_json("Return only JSON but calculate it yourself.", "not json")


def test_detection() -> None:
    assert requests_strict_json("Return ONLY strict JSON: {\"ok\":true}")
    assert not requests_strict_json("Explain JSON to me")
