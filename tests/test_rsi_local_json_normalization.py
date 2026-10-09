from __future__ import annotations

import pytest

from sophyane.rsi.local_intelligence import LocalIntelligenceRouter


VALID = (
    '{"hypothesis":"gap",'
    '"files":{"src/example.py":"replacement"}}'
)


CASES = (
    (
        "raw_json",
        VALID,
        True,
    ),
    (
        "fenced_json",
        "```json\n" + VALID + "\n```",
        True,
    ),
    (
        "fenced_plain",
        "```\n" + VALID + "\n```",
        True,
    ),
    (
        "prose_prefix",
        "Here is the result:\n" + VALID,
        False,
    ),
    (
        "multiple_fences",
        "```json\n"
        + VALID
        + "\n```\n```json\n"
        + VALID
        + "\n```",
        False,
    ),
    (
        "malformed",
        '```json\n{"hypothesis":\n```',
        False,
    ),
)


def analyze(raw: str):
    router = LocalIntelligenceRouter(
        {
            "qwen": lambda context, role: raw,
        }
    )

    result = router.analyze(
        {"problem": "parser contract"},
        route="qwen",
    )

    assert len(result) == 1
    return result[0]


@pytest.mark.parametrize(
    "name,raw,should_parse",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_local_router_json_envelope_contract(
    name,
    raw,
    should_parse,
):
    proposal = analyze(raw)

    if should_parse:
        assert proposal.text == "gap"
        assert proposal.files == {
            "src/example.py": "replacement"
        }
    else:
        # Rejected envelopes must never acquire mutation data.
        assert proposal.files == {}


def test_raw_json_existing_contract_is_green():
    proposal = analyze(VALID)

    assert proposal.text == "gap"
    assert proposal.files == {
        "src/example.py": "replacement"
    }
