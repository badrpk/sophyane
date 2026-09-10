from __future__ import annotations

import pytest

from sophyane.providers import nifdu_cdp_bridge as bridge


def _page(name):
    return {
        "id": name,
        "type": "page",
        "title": name,
        "url": f"https://chatgpt.com/c/{name}",
        "webSocketDebuggerUrl": f"ws://example/{name}",
    }


class FakeCDP:
    closed = []

    def __init__(self, page):
        self.page = page

    def close(self):
        self.closed.append(
            self.page["id"]
        )


def test_chat_page_prefers_interactive_candidate(
    monkeypatch,
):
    usable = _page("usable")
    exhausted = _page("exhausted")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            usable,
            exhausted,
        ],
    )

    FakeCDP.closed = []

    monkeypatch.setattr(
        bridge,
        "CDP",
        FakeCDP,
    )

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        lambda cdp: {
            "interactive":
                cdp.page["id"]
                == "usable",
            "reason":
                (
                    "ready"
                    if cdp.page["id"] == "usable"
                    else "chatgpt_usage_limit"
                ),
        },
    )

    selected = bridge.chat_page()

    assert selected["id"] == "usable"

    assert FakeCDP.closed == [
        "exhausted",
        "usable",
    ]


def test_chat_page_preserves_last_match_fallback(
    monkeypatch,
):
    first = _page("first")
    last = _page("last")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            first,
            last,
        ],
    )

    FakeCDP.closed = []

    monkeypatch.setattr(
        bridge,
        "CDP",
        FakeCDP,
    )

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        lambda _cdp: {
            "interactive": False,
            "reason": "chatgpt_usage_limit",
        },
    )

    selected = bridge.chat_page()

    assert selected["id"] == "last"


def test_chat_page_skips_probe_failure(
    monkeypatch,
):
    usable = _page("usable")
    broken = _page("broken")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            usable,
            broken,
        ],
    )

    class SelectiveCDP(FakeCDP):
        def __init__(self, page):
            if page["id"] == "broken":
                raise RuntimeError(
                    "stale target"
                )

            super().__init__(page)

    monkeypatch.setattr(
        bridge,
        "CDP",
        SelectiveCDP,
    )

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        lambda _cdp: {
            "interactive": True,
            "reason": "ready",
        },
    )

    selected = bridge.chat_page()

    assert selected["id"] == "usable"


def test_chat_page_requires_chatgpt_target(
    monkeypatch,
):
    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            {
                "id": "other",
                "type": "page",
                "title": "Other",
                "url": "https://example.com/",
            }
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="No ChatGPT Chromium tab found",
    ):
        bridge.chat_page()


def test_chat_page_does_not_fallback_to_transport_broken_target(
    monkeypatch,
):
    broken = _page("broken")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            broken,
        ],
    )

    FakeCDP.closed = []

    monkeypatch.setattr(
        bridge,
        "CDP",
        FakeCDP,
    )

    def broken_readiness(_cdp):
        raise TimeoutError(
            "CDP Runtime.evaluate timed out "
            "after 3.000s."
        )

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        broken_readiness,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "No responsive ChatGPT CDP target"
        ),
    ) as excinfo:
        bridge.chat_page()

    assert (
        "TimeoutError"
        in str(excinfo.value)
    )

    assert FakeCDP.closed == [
        "broken",
    ]


def test_chat_page_uses_responsive_semantic_fallback_not_broken_last_match(
    monkeypatch,
):
    responsive = _page("responsive")
    broken = _page("broken")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            responsive,
            broken,
        ],
    )

    FakeCDP.closed = []

    monkeypatch.setattr(
        bridge,
        "CDP",
        FakeCDP,
    )

    def readiness(cdp):
        if cdp.page["id"] == "broken":
            raise TimeoutError(
                "synthetic transport timeout"
            )

        return {
            "interactive": False,
            "reason": "chatgpt_usage_limit",
        }

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        readiness,
    )

    selected = bridge.chat_page()

    assert (
        selected["id"]
        == "responsive"
    )


def test_chat_page_preserves_last_responsive_semantic_fallback(
    monkeypatch,
):
    first = _page("first")
    last = _page("last")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            first,
            last,
        ],
    )

    FakeCDP.closed = []

    monkeypatch.setattr(
        bridge,
        "CDP",
        FakeCDP,
    )

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        lambda _cdp: {
            "interactive": False,
            "reason":
                "chatgpt_usage_limit",
        },
    )

    selected = bridge.chat_page()

    # reversed(matches) probes the historical last match first.
    # Once that target has proven transport-responsive, it remains
    # the preferred semantic fallback.
    assert selected["id"] == "last"


def test_chat_page_assigns_each_candidate_a_fair_call_budget(
    monkeypatch,
):
    healthy = _page("healthy")
    broken = _page("broken")

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [
            healthy,
            broken,
        ],
    )

    observed = []

    class BudgetCDP(FakeCDP):
        def __init__(self, page):
            super().__init__(page)
            self.call_timeout = 10.0

    monkeypatch.setattr(
        bridge,
        "CDP",
        BudgetCDP,
    )

    def readiness(cdp):
        observed.append(
            (
                cdp.page["id"],
                cdp.call_timeout,
            )
        )

        if cdp.page["id"] == "broken":
            raise TimeoutError(
                "synthetic broken target"
            )

        return {
            "interactive": True,
            "reason": "ready",
        }

    monkeypatch.setattr(
        bridge,
        "chatgpt_readiness",
        readiness,
    )

    monkeypatch.setattr(
        bridge,
        "TIMEOUT",
        3,
    )

    selected = bridge.chat_page()

    assert selected["id"] == "healthy"

    assert [
        item[0]
        for item in observed
    ] == [
        "broken",
        "healthy",
    ]

    # With two candidates and a three-second global readiness window,
    # the first candidate must not inherit the full three-second CDP
    # call timeout.
    assert observed[0][1] < 3.0

    assert observed[0][1] <= 1.5
