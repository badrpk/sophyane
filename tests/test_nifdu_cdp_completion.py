from __future__ import annotations

from pathlib import Path


BRIDGE = Path(
    "src/sophyane/providers/nifdu_cdp_bridge.py"
)


def _source() -> str:
    return BRIDGE.read_text(
        encoding="utf-8",
    )


def test_new_assistant_node_alone_is_not_completion_proof():
    source = _source()

    assert (
        "SOPHYANE_NIFDU_RESPONSE_COMPLETION_AUTHORITY_V11"
        in source
    )

    assert (
        "observed_stream_completion = bool("
        in source
    )

    block_start = source.index(
        "observed_stream_completion = bool("
    )

    block_end = source.index(
        "if text != previous:",
        block_start,
    )

    block = source[
        block_start:block_end
    ]

    assert (
        "new_user_turn_seen"
        in block
    )

    assert (
        "streaming_seen"
        in block
    )

    assert (
        "not streaming"
        in block
    )

    # A mere new assistant-node count must no longer authorize
    # immediate return.
    assert (
        "count > before_count"
        not in block
    )


def test_observed_stream_end_uses_bounded_dom_settlement():
    import ast

    source = _source()
    tree = ast.parse(source)

    matches = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.If,
        ):
            continue

        if (
            ast.unparse(
                node.test
            )
            != "observed_stream_completion"
        ):
            continue

        matches.append(
            node
        )

    assert len(matches) == 1

    gate = matches[0]

    assert len(gate.body) >= 1

    rendered = "\n".join(
        ast.unparse(item)
        for item in gate.body
    )

    assert (
        "settle_completed_assistant_text"
        in rendered
    )

    assert (
        "return text"
        not in rendered
    )


def test_post_stream_settlement_requires_stable_non_streaming_dwell():
    source = _source()

    assert (
        "SOPHYANE_CDP_POST_STREAM_DOM_SETTLEMENT_V2"
        in source
    )

    assert (
        "timeout=3.0"
        in source
    )

    assert (
        "interval=0.25"
        in source
    )

    assert (
        "stable_for=1.0"
        in source
    )

    assert (
        "stable_since = None"
        in source
    )

    assert (
        "if current != previous:"
        in source
    )

    assert (
        "now"
        in source
    )

    assert (
        "- stable_since"
        in source
    )

    assert (
        "if streaming:"
        in source
    )


def test_unproven_fresh_response_uses_stability_fallback():
    source = _source()

    marker = source.index(
        "SOPHYANE_NIFDU_RESPONSE_COMPLETION_AUTHORITY_V11"
    )

    stability = source.index(
        "stable_since",
        marker,
    )

    return_gate = source.index(
        ">= 2.0",
        marker,
    )

    assert stability < return_gate


def test_timeout_authority_is_unchanged():
    source = _source()

    assert (
        "time.monotonic() < deadline"
        in source
    )

    assert (
        'raise TimeoutError('
        in source
    )

    assert (
        '"Timed out waiting for ChatGPT."'
        in source
    )

def test_chatgpt_readiness_accepts_interactive_composer():
    from sophyane.providers import nifdu_cdp_bridge

    class FakeCdp:
        def evaluate(
            self,
            expression,
        ):
            assert "challengeTitle" in expression
            assert "promptTextarea" in expression

            return {
                "href": "https://chatgpt.com/",
                "title": "ChatGPT",
                "readyState": "complete",
                "bodyChars": 100,
                "promptTextarea": True,
                "textarea": False,
                "editable": True,
                "challengeTitle": False,
                "challengeBody": False,
                "cloudflareFrame": False,
                "challenged": False,
                "composer": True,
                "interactive": True,
            }

    result = (
        nifdu_cdp_bridge.chatgpt_readiness(
            FakeCdp()
        )
    )

    assert result["interactive"] is True
    assert result["challenged"] is False
    assert result["reason"] == "ready"


def test_chatgpt_readiness_rejects_cloudflare_challenge():
    from sophyane.providers import nifdu_cdp_bridge

    class FakeCdp:
        def evaluate(
            self,
            expression,
        ):
            return {
                "href": "https://chatgpt.com/",
                "title": "Just a moment...",
                "readyState": "complete",
                "bodyChars": 0,
                "promptTextarea": False,
                "textarea": False,
                "editable": False,
                "challengeTitle": True,
                "challengeBody": False,
                "cloudflareFrame": True,
                "challenged": True,
                "composer": False,
                "interactive": False,
            }

    result = (
        nifdu_cdp_bridge.chatgpt_readiness(
            FakeCdp()
        )
    )

    assert result["interactive"] is False
    assert result["challenged"] is True
    assert (
        result["reason"]
        == "browser_verification_challenge"
    )


def test_wait_prompt_fails_fast_on_browser_verification(
    monkeypatch,
):
    from sophyane.providers import nifdu_cdp_bridge

    monkeypatch.setattr(
        nifdu_cdp_bridge,
        "chatgpt_readiness",
        lambda cdp: {
            "interactive": False,
            "challenged": True,
            "composer": False,
            "reason": (
                "browser_verification_challenge"
            ),
        },
    )

    class FakeCdp:
        pass

    try:
        nifdu_cdp_bridge.wait_prompt(
            FakeCdp()
        )

    except RuntimeError as error:
        message = str(
            error
        )

        assert (
            "browser verification challenge"
            in message
        )

        assert (
            "CDP transport is ready"
            in message
        )

    else:
        raise AssertionError(
            "wait_prompt should fail fast on challenge"
        )


def test_structured_response_with_empty_terminal_reason_is_incomplete():
    from sophyane.providers.nifdu_cdp_bridge import (
        structured_response_semantically_complete,
    )

    response = (
        "STATUS: CONTINUE\n"
        "NEXT_MODE3_INSTRUCTION:\n"
        "Make one bounded change.\n"
        "REASON:\n"
    )

    assert (
        structured_response_semantically_complete(
            response
        )
        is False
    )


def test_structured_response_with_reason_body_is_complete():
    from sophyane.providers.nifdu_cdp_bridge import (
        structured_response_semantically_complete,
    )

    response = (
        "STATUS: CONTINUE\n"
        "NEXT_MODE3_INSTRUCTION:\n"
        "Make one bounded change.\n"
        "REASON:\n"
        "The bounded change is supported by repository evidence.\n"
    )

    assert (
        structured_response_semantically_complete(
            response
        )
        is True
    )


def test_structured_success_with_empty_evidence_is_incomplete():
    from sophyane.providers.nifdu_cdp_bridge import (
        structured_response_semantically_complete,
    )

    assert (
        structured_response_semantically_complete(
            "STATUS: SUCCESS\nEVIDENCE:\n"
        )
        is False
    )


def test_nonstructured_chat_response_remains_complete():
    from sophyane.providers.nifdu_cdp_bridge import (
        structured_response_semantically_complete,
    )

    assert (
        structured_response_semantically_complete(
            "Ordinary completed assistant response."
        )
        is True
    )


def test_post_stream_settlement_cannot_return_incomplete_structured_timeout():
    import ast
    from pathlib import Path

    source = Path(
        "src/sophyane/providers/nifdu_cdp_bridge.py"
    ).read_text(
        encoding="utf-8",
    )

    tree = ast.parse(source)

    function = next(
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name
            == "settle_completed_assistant_text"
        )
    )

    rendered = ast.unparse(
        function
    )

    assert (
        "SOPHYANE_CDP_STRUCTURED_TIMEOUT_FAIL_CLOSED_V1"
        in source
    )

    assert (
        "not structured_response_semantically_complete(previous)"
        in rendered
    )

    assert (
        "raise TimeoutError"
        in rendered
    )

    assert (
        "Structured ChatGPT response did not finish"
        in source
    )


def test_chatgpt_readiness_classifies_explicit_signed_out_state():
    from sophyane.providers import nifdu_cdp_bridge

    class FakeCdp:
        def evaluate(
            self,
            expression,
        ):
            assert "loginControl" in expression
            assert "signedOut" in expression

            return {
                "href": "https://chatgpt.com/",
                "title": "ChatGPT",
                "readyState": "complete",
                "bodyChars": 120,
                "promptTextarea": False,
                "textarea": False,
                "editable": False,
                "challengeTitle": False,
                "challengeBody": False,
                "cloudflareFrame": False,
                "challenged": False,
                "loginControl": True,
                "signedOut": True,
                "composer": False,
                "interactive": False,
            }

    result = (
        nifdu_cdp_bridge.chatgpt_readiness(
            FakeCdp()
        )
    )

    assert result["interactive"] is False
    assert result["challenged"] is False
    assert result["signedOut"] is True
    assert result["reason"] == "chatgpt_signed_out"


def test_wait_prompt_fails_fast_on_signed_out_state(
    monkeypatch,
):
    from sophyane.providers import nifdu_cdp_bridge

    monkeypatch.setattr(
        nifdu_cdp_bridge,
        "chatgpt_readiness",
        lambda cdp: {
            "interactive": False,
            "challenged": False,
            "signedOut": True,
            "composer": False,
            "reason": "chatgpt_signed_out",
        },
    )

    class FakeCdp:
        pass

    try:
        nifdu_cdp_bridge.wait_prompt(
            FakeCdp()
        )
    except RuntimeError as error:
        message = str(error)

        assert "signed out" in message
        assert "sign in manually" in message
        assert "persistent NIFDU Chromium profile" in message
        assert "CDP transport is ready" in message
    else:
        raise AssertionError(
            "wait_prompt should fail fast on signed-out state"
        )
