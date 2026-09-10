from __future__ import annotations

import json

from sophyane.discovery_provider_reasoner import (
    _normalize_provider_response,
)


def test_generate_hypotheses_candidates_alias_is_normalized():
    raw = json.dumps(
        {
            "objective": "test",
            "candidates": [
                {
                    "statement": (
                        "Failure penalties reduce "
                        "repeated failed selection."
                    ),
                    "rationale": (
                        "Static ranking ignores "
                        "outcomes."
                    ),
                    "predictions": [
                        "repeat failures decrease"
                    ],
                    "assumptions": [
                        "history is available"
                    ],
                }
            ],
            "selected_index": 0,
        }
    )

    normalized = (
        _normalize_provider_response(
            "generate_hypotheses",
            raw,
        )
    )

    parsed = json.loads(
        normalized
    )

    assert "hypotheses" in parsed

    assert (
        parsed["hypotheses"][0]["statement"]
        == (
            "Failure penalties reduce "
            "repeated failed selection."
        )
    )

    assert (
        parsed["_sophyane_normalization"][
            "source_field"
        ]
        == "candidates"
    )

    assert (
        parsed["_sophyane_normalization"][
            "semantic_content_invented"
        ]
        is False
    )


def test_canonical_hypotheses_response_is_unchanged():
    raw = json.dumps(
        {
            "hypotheses": [
                {
                    "statement": "canonical",
                }
            ]
        }
    )

    normalized = (
        _normalize_provider_response(
            "generate_hypotheses",
            raw,
        )
    )

    assert normalized == raw


def test_alias_is_not_applied_to_other_operations():
    raw = json.dumps(
        {
            "candidates": [
                {
                    "statement": "candidate",
                }
            ]
        }
    )

    normalized = (
        _normalize_provider_response(
            "generate_candidate",
            raw,
        )
    )

    assert normalized == raw


def test_invalid_json_is_preserved():
    raw = "not json"

    assert (
        _normalize_provider_response(
            "generate_hypotheses",
            raw,
        )
        == raw
    )


def test_empty_candidate_items_do_not_create_hypotheses():
    raw = json.dumps(
        {
            "candidates": [
                {},
                {
                    "statement": "",
                },
            ]
        }
    )

    normalized = (
        _normalize_provider_response(
            "generate_hypotheses",
            raw,
        )
    )

    parsed = json.loads(
        normalized
    )

    assert "hypotheses" not in parsed


def test_whole_json_markdown_fence_is_stripped():
    import json

    from sophyane.discovery_provider_reasoner import (
        _normalize_provider_response,
        _operation_response_usable,
    )

    raw = """```json
{
  "hypotheses": [
    {
      "statement": "Failure-aware reranking reduces repeat failures.",
      "rationale": "Previously failed candidates receive a penalty.",
      "predictions": [
        "Repeat failed selections decrease."
      ],
      "assumptions": [
        "Failure history is available."
      ]
    }
  ]
}
```"""

    normalized = _normalize_provider_response(
        "generate_hypotheses",
        raw,
    )

    parsed = json.loads(
        normalized
    )

    assert (
        parsed["hypotheses"][0]["statement"]
        == (
            "Failure-aware reranking reduces "
            "repeat failures."
        )
    )

    assert (
        _operation_response_usable(
            "generate_hypotheses",
            normalized,
        )
        is True
    )


def test_plain_whole_json_fence_is_stripped():
    import json

    from sophyane.discovery_provider_reasoner import (
        _normalize_provider_response,
    )

    raw = """```
{"hypotheses":[{"statement":"x"}]}
```"""

    normalized = _normalize_provider_response(
        "generate_hypotheses",
        raw,
    )

    assert json.loads(
        normalized
    ) == {
        "hypotheses": [
            {
                "statement": "x",
            }
        ]
    }


def test_invalid_json_fence_is_preserved():
    from sophyane.discovery_provider_reasoner import (
        _normalize_provider_response,
    )

    raw = """```json
not valid json
```"""

    assert (
        _normalize_provider_response(
            "generate_hypotheses",
            raw,
        )
        == raw
    )


def test_json_fence_embedded_in_prose_is_not_extracted():
    from sophyane.discovery_provider_reasoner import (
        _normalize_provider_response,
    )

    raw = (
        "Here is the answer:\n"
        "```json\n"
        '{"hypotheses":[{"statement":"x"}]}\n'
        "```"
    )

    assert (
        _normalize_provider_response(
            "generate_hypotheses",
            raw,
        )
        == raw
    )
