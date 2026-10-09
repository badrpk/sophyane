from __future__ import annotations

import os
from types import SimpleNamespace


def test_mode4_leaf_bootstraps_browser_before_external_bridge(
    monkeypatch,
):
    from sophyane.browser import launcher
    from sophyane.providers import nifdu_leaf_adapter

    events: list[str] = []

    def fake_launch_nifdu_browser():
        events.append("bootstrap")
        return {
            "ok": True,
            "reused": True,
            "launched": False,
        }

    def fake_bridge_ask(prompt, site):
        events.append(f"ask:{site}:{prompt}")
        return "leaf-result"

    monkeypatch.setattr(
        launcher,
        "launch_nifdu_browser",
        fake_launch_nifdu_browser,
    )
    monkeypatch.setattr(
        nifdu_leaf_adapter,
        "_load_external_bridge",
        lambda: SimpleNamespace(ask=fake_bridge_ask),
    )
    monkeypatch.setenv(
        "SOPHYANE_NIFDU_SITE",
        "chatgpt",
    )

    assert nifdu_leaf_adapter.ask("hello") == "leaf-result"
    assert events == [
        "bootstrap",
        "ask:chatgpt:hello",
    ]


def test_mode4_leaf_fails_closed_when_browser_bootstrap_fails(
    monkeypatch,
):
    from sophyane.browser import launcher
    from sophyane.providers import nifdu_leaf_adapter
    from sophyane.providers.base import ProviderError

    bridge_called = False

    def fake_launch_nifdu_browser():
        return {
            "ok": False,
            "error": "CDP unavailable",
        }

    def fake_bridge_ask(prompt, site):
        nonlocal bridge_called
        bridge_called = True
        return "must-not-run"

    monkeypatch.setattr(
        launcher,
        "launch_nifdu_browser",
        fake_launch_nifdu_browser,
    )
    monkeypatch.setattr(
        nifdu_leaf_adapter,
        "_load_external_bridge",
        lambda: SimpleNamespace(ask=fake_bridge_ask),
    )
    monkeypatch.setenv(
        "SOPHYANE_NIFDU_SITE",
        "chatgpt",
    )

    try:
        nifdu_leaf_adapter.ask("hello")
    except ProviderError as error:
        assert "browser bootstrap failed" in str(error).lower()
        assert "CDP unavailable" in str(error)
    else:
        raise AssertionError(
            "Mode-4 NIFDU must fail closed when browser bootstrap fails"
        )

    assert bridge_called is False


def test_termux_nifdu_launcher_uses_real_chromium_subprocess(
    monkeypatch,
    tmp_path,
):
    from sophyane.browser import launcher

    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return FakeProcess()

    chromium = (
        "/data/data/com.termux/files/usr/"
        "lib/chromium/chrome"
    )

    monkeypatch.setattr(
        launcher,
        "NIFDU_BROWSER_PROFILE",
        tmp_path / "profile",
    )
    monkeypatch.setattr(
        launcher,
        "find_chromium",
        lambda: chromium,
    )
    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_ready",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        launcher,
        "_wait_for_nifdu_cdp",
        lambda *args, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        fake_popen,
    )

    monkeypatch.setenv(
        "PREFIX",
        "/data/data/com.termux/files/usr",
    )
    monkeypatch.setenv(
        "LD_PRELOAD",
        "/data/data/com.termux/files/usr/"
        "lib/libtermux-exec.so",
    )
    monkeypatch.setenv("DISPLAY", ":2")

    state = launcher.launch_nifdu_browser()

    assert state["ok"] is True

    args = captured["args"]

    assert (
        "--browser-subprocess-path="
        "/data/data/com.termux/files/usr/"
        "lib/chromium/chrome"
    ) in args

    assert not any(
        str(arg).startswith(
            "--enable-features=NetworkServiceInProcess"
        )
        for arg in args
    )


def test_external_nifdu_bridge_preserves_chat_target_across_turns(
    monkeypatch,
):
    """
    Browser conversation context belongs to one persistent Chromium target.
    Reordering /json results must not move a Mode-4 NIFDU session to another
    ChatGPT conversation.
    """
    from sophyane.providers import nifdu_leaf_adapter

    bridge = nifdu_leaf_adapter._load_external_bridge()

    first = {
        "id": "conversation-a",
        "type": "page",
        "url": "https://chatgpt.com/c/conversation-a",
        "webSocketDebuggerUrl": "ws://example/a",
    }
    second = {
        "id": "conversation-b",
        "type": "page",
        "url": "https://chatgpt.com/c/conversation-b",
        "webSocketDebuggerUrl": "ws://example/b",
    }

    bridge._SESSION_TARGETS.clear()

    snapshots = iter(
        [
            [first, second],
            [second, first],
        ]
    )

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: next(snapshots),
    )

    selected_first = bridge.ensure_page("chatgpt")
    selected_second = bridge.ensure_page("chatgpt")

    assert selected_first["id"] == "conversation-a"
    assert selected_second["id"] == "conversation-a"


def test_external_nifdu_bridge_rebinds_when_bound_target_disappears(
    monkeypatch,
):
    from sophyane.providers import nifdu_leaf_adapter

    bridge = nifdu_leaf_adapter._load_external_bridge()

    first = {
        "id": "conversation-a",
        "type": "page",
        "url": "https://chatgpt.com/c/conversation-a",
        "webSocketDebuggerUrl": "ws://example/a",
    }
    replacement = {
        "id": "conversation-b",
        "type": "page",
        "url": "https://chatgpt.com/c/conversation-b",
        "webSocketDebuggerUrl": "ws://example/b",
    }

    bridge._SESSION_TARGETS.clear()

    snapshots = iter(
        [
            [first],
            [replacement],
        ]
    )

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: next(snapshots),
    )

    assert bridge.ensure_page("chatgpt")["id"] == "conversation-a"
    assert bridge.ensure_page("chatgpt")["id"] == "conversation-b"


def test_present_nifdu_target_activates_bound_cdp_page(
    monkeypatch,
):
    from sophyane.browser import launcher

    calls = []

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_endpoint",
        lambda: ("127.0.0.1", 9222),
    )

    def fake_urlopen(request, timeout=0):
        calls.append(
            (
                request.full_url,
                request.get_method(),
                timeout,
            )
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        return Response()

    monkeypatch.setattr(
        launcher.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    result = launcher.activate_nifdu_target(
        "conversation-a"
    )

    assert result["ok"] is True
    assert calls == [
        (
            "http://127.0.0.1:9222/json/activate/conversation-a",
            "GET",
            5,
        )
    ]


def test_open_nifdu_target_creates_second_cdp_tab(
    monkeypatch,
):
    from sophyane.browser import launcher

    seen = {}

    monkeypatch.setattr(
        launcher,
        "_nifdu_cdp_endpoint",
        lambda: ("127.0.0.1", 9222),
    )

    def fake_urlopen(request, timeout=0):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return (
                    b'{"id":"game-preview","type":"page"}'
                )

        return Response()

    monkeypatch.setattr(
        launcher.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    result = launcher.open_nifdu_target(
        "http://127.0.0.1:8765/index.html?v=123"
    )

    assert result["ok"] is True
    assert result["target"]["id"] == "game-preview"
    assert seen["method"] == "PUT"
    assert "/json/new?" in seen["url"]
    assert "127.0.0.1" in seen["url"]


def test_present_nifdu_browser_requires_visible_display(
    monkeypatch,
):
    from sophyane.browser import launcher

    monkeypatch.delenv(
        "DISPLAY",
        raising=False,
    )
    monkeypatch.delenv(
        "WAYLAND_DISPLAY",
        raising=False,
    )

    result = launcher.present_nifdu_browser(
        "conversation-a"
    )

    assert result["ok"] is False
    assert result["reason"] == "visible_display_unavailable"


def test_present_nifdu_browser_activates_target_and_foregrounds_termux_x11(
    monkeypatch,
):
    from sophyane.browser import launcher

    monkeypatch.setenv("DISPLAY", ":2")
    monkeypatch.delenv(
        "WAYLAND_DISPLAY",
        raising=False,
    )

    activated = []
    commands = []

    monkeypatch.setattr(
        launcher,
        "activate_nifdu_target",
        lambda target_id: (
            activated.append(target_id)
            or {
                "ok": True,
                "target_id": target_id,
            }
        ),
    )

    monkeypatch.setattr(
        launcher.shutil,
        "which",
        lambda name: (
            "/data/data/com.termux/files/usr/bin/am"
            if name == "am"
            else None
        ),
    )

    def fake_run(command, **kwargs):
        commands.append(command)

        class Result:
            returncode = 0
            stdout = (
                "Starting: Intent "
                "{ cmp=com.termux.x11/.MainActivity }\n"
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        fake_run,
    )

    result = launcher.present_nifdu_browser(
        "conversation-a"
    )

    assert result["ok"] is True
    assert result["activated"] is True
    assert result["presented"] is True
    assert activated == ["conversation-a"]

    assert commands == [
        [
            "/data/data/com.termux/files/usr/bin/am",
            "start",
            "--user",
            "0",
            "-n",
            "com.termux.x11/.MainActivity",
        ]
    ]


def test_external_chatgpt_wait_prompt_reports_signed_out_target(
    monkeypatch,
):
    from sophyane.providers import nifdu_leaf_adapter

    bridge = nifdu_leaf_adapter._load_external_bridge()

    page = {
        "id": "conversation-a",
        "type": "page",
        "url": "https://chatgpt.com/c/conversation-a",
        "webSocketDebuggerUrl": "ws://example/a",
    }

    class FakeCDP:
        def evaluate(self, script):
            return {
                "composer": False,
                "challenged": False,
                "signedOut": True,
                "reason": "chatgpt_signed_out",
            }

    with __import__("pytest").raises(
        bridge.HumanInteractionRequired
    ) as caught:
        bridge.wait_prompt(
            FakeCDP(),
            site="chatgpt",
            page=page,
        )

    error = caught.value

    assert error.site == "chatgpt"
    assert error.target_id == "conversation-a"
    assert error.reason == "chatgpt_signed_out"


def test_external_chatgpt_wait_prompt_reports_verification_target(
    monkeypatch,
):
    from sophyane.providers import nifdu_leaf_adapter

    bridge = nifdu_leaf_adapter._load_external_bridge()

    page = {
        "id": "conversation-a",
        "type": "page",
        "url": "https://chatgpt.com/c/conversation-a",
        "webSocketDebuggerUrl": "ws://example/a",
    }

    class FakeCDP:
        def evaluate(self, script):
            return {
                "composer": False,
                "challenged": True,
                "signedOut": False,
                "reason": "browser_verification_challenge",
            }

    with __import__("pytest").raises(
        bridge.HumanInteractionRequired
    ) as caught:
        bridge.wait_prompt(
            FakeCDP(),
            site="chatgpt",
            page=page,
        )

    error = caught.value

    assert error.target_id == "conversation-a"
    assert (
        error.reason
        == "browser_verification_challenge"
    )


def test_mode4_nifdu_human_interaction_presents_bound_target(
    monkeypatch,
):
    from sophyane.browser import launcher
    from sophyane.providers import nifdu_leaf_adapter

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_SITE",
        "chatgpt",
    )

    monkeypatch.setattr(
        launcher,
        "launch_nifdu_browser",
        lambda: {
            "ok": True,
            "reused": True,
        },
    )

    bridge = nifdu_leaf_adapter._load_external_bridge()

    def require_human(prompt, site):
        raise bridge.HumanInteractionRequired(
            site=site,
            target_id="conversation-a",
            reason="chatgpt_signed_out",
        )

    monkeypatch.setattr(
        bridge,
        "ask",
        require_human,
    )

    monkeypatch.setattr(
        nifdu_leaf_adapter,
        "_load_external_bridge",
        lambda: bridge,
    )

    presented = []

    monkeypatch.setattr(
        launcher,
        "present_nifdu_browser",
        lambda target_id: (
            presented.append(target_id)
            or {
                "ok": True,
                "presented": True,
            }
        ),
    )

    with __import__("pytest").raises(
        nifdu_leaf_adapter.ProviderError
    ) as caught:
        nifdu_leaf_adapter.ask(
            "make snake game"
        )

    assert presented == ["conversation-a"]

    message = str(caught.value).lower()
    assert "manual" in message
    assert "sign" in message
