from __future__ import annotations

import time

import pytest

from sophyane.providers import nifdu_cdp_bridge as bridge
from sophyane.session_banner import _nifdu_reason_label


class FakeReadinessCDP:
    def evaluate(self, _script):
        return {
            "href": "https://chatgpt.com/",
            "title": "ChatGPT",
            "readyState": "complete",
            "bodyChars": 100,
            "promptTextarea": True,
            "textarea": True,
            "editable": True,
            "challengeTitle": False,
            "challengeBody": False,
            "cloudflareFrame": False,
            "challenged": False,
            "loginControl": False,
            "signedOut": False,
            "usageLimited": True,
            "tryAgainText": "try again at 6:39 PM",
            "composer": True,
            "interactive": False,
        }


def test_usage_limit_overrides_visible_composer():
    state = bridge.chatgpt_readiness(
        FakeReadinessCDP()
    )

    assert state["composer"] is True
    assert state["usageLimited"] is True
    assert state["interactive"] is False
    assert state["reason"] == "chatgpt_usage_limit"


def test_wait_prompt_usage_limit_fails_fast(
    monkeypatch,
):
    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        lambda _cdp: {
            "interactive": False,
            "challenged": False,
            "signedOut": False,
            "usageLimited": True,
            "tryAgainText": "try again at 6:39 PM",
            "reason": "chatgpt_usage_limit",
        },
    )

    started = time.monotonic()

    with pytest.raises(
        RuntimeError,
        match="usage limit reached",
    ) as exc:
        bridge.wait_prompt(
            object()
        )

    elapsed = (
        time.monotonic()
        - started
    )

    assert elapsed < 1.0
    assert "6:39 PM" in str(
        exc.value
    )


def test_usage_limit_banner_label():
    assert (
        _nifdu_reason_label(
            "chatgpt_usage_limit"
        )
        == "Usage limit reached"
    )


class FakeStaleHistoricalQuotaCDP:
    def evaluate(self, _script):
        return {
            "href": (
                "https://chatgpt.com/c/example"
            ),
            "title": "Old quota conversation",
            "readyState": "complete",
            "bodyChars": 2000,
            "promptTextarea": True,
            "textarea": True,
            "editable": True,
            "challengeTitle": False,
            "challengeBody": False,
            "cloudflareFrame": False,
            "challenged": False,
            "loginControl": False,
            "signedOut": False,

            # Historical body text may contain quota wording, but
            # ACTIVE quota state must be false.
            "usageLimited": False,
            "activeUsageLimit": False,
            "activeUsageLimitText": "",
            "quotaCandidateCount": 0,
            "tryAgainText": "",

            "composer": True,
            "interactive": True,
        }


def test_historical_quota_message_does_not_block_composer():
    state = bridge.chatgpt_readiness(
        FakeStaleHistoricalQuotaCDP()
    )

    assert state[
        "composer"
    ] is True

    assert state[
        "usageLimited"
    ] is False

    assert state[
        "interactive"
    ] is True

    assert state[
        "reason"
    ] == "ready"


class FakeActiveQuotaV2CDP:
    def evaluate(self, _script):
        return {
            "href": "https://chatgpt.com/",
            "title": "ChatGPT",
            "readyState": "complete",
            "bodyChars": 100,
            "promptTextarea": True,
            "textarea": True,
            "editable": True,
            "challengeTitle": False,
            "challengeBody": False,
            "cloudflareFrame": False,
            "challenged": False,
            "loginControl": False,
            "signedOut": False,
            "usageLimited": True,
            "activeUsageLimit": True,
            "activeUsageLimitText": (
                "You've hit your usage limit. "
                "Try again at 9:15 PM."
            ),
            "quotaCandidateCount": 1,
            "tryAgainText": (
                "Try again at 9:15 PM"
            ),
            "composer": True,
            "interactive": False,
        }


def test_active_quota_v2_still_blocks_generation():
    state = bridge.chatgpt_readiness(
        FakeActiveQuotaV2CDP()
    )

    assert state[
        "usageLimited"
    ] is True

    assert state[
        "activeUsageLimit"
    ] is True

    assert state[
        "quotaCandidateCount"
    ] == 1

    assert state[
        "interactive"
    ] is False

    assert state[
        "reason"
    ] == "chatgpt_usage_limit"

    assert (
        "9:15 PM"
        in state[
            "tryAgainText"
        ]
    )


def test_readiness_source_detects_active_work_usage_shell():
    from pathlib import Path

    source = Path(
        "src/sophyane/providers/nifdu_cdp_bridge.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_CDP_CHATGPT_ACTIVE_WORK_USAGE_LIMIT_V1"
        in source
    )

    assert (
        "out of work usage for now"
        in source.lower()
    )

    assert (
        "activeWorkUsageNotice"
        in source
    )

    assert (
        "quotaCandidates.length > 0"
        in source
    )

    assert (
        "|| activeWorkUsageNotice"
        in source
    )


def test_active_work_usage_is_exposed_in_readiness_payload():
    from pathlib import Path

    source = Path(
        "src/sophyane/providers/nifdu_cdp_bridge.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "activeWorkUsageNotice,"
        in source
    )

    assert (
        "activeWorkUsageText,"
        in source
    )

    assert (
        "wait for your usage to reset at"
        in source.lower()
    )
