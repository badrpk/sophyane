from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from sophyane.browser import cli as browser_cli
from sophyane.browser import launcher
from sophyane.browser.cdp import CDPEndpoint, CDPError, _assert_loopback


def test_browser_parser_accepts_start_cdp() -> None:
    args = browser_cli.build_browser_parser().parse_args(["start", "--cdp"])
    assert args.browser_command == "start"
    assert args.cdp is True


def test_browser_parser_accepts_status() -> None:
    args = browser_cli.build_browser_parser().parse_args(["status", "--port", "9222"])
    assert args.browser_command == "status"
    assert args.host == "127.0.0.1"
    assert args.port == 9222


def test_non_loopback_cdp_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("10.0.0.8", 0))],
    )
    with pytest.raises(CDPError):
        _assert_loopback("example.invalid")


def test_loopback_cdp_allowed() -> None:
    _assert_loopback("127.0.0.1")
    _assert_loopback("localhost")


def test_launcher_adds_loopback_remote_debugging_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(launcher, "STATE_DIR", tmp_path)
    monkeypatch.setattr(launcher, "BROWSER_PROFILE", tmp_path / "profile")
    monkeypatch.setattr(launcher, "CDP_PORT_FILE", tmp_path / "cdp-port")
    monkeypatch.setattr(launcher, "find_chromium", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(launcher, "_free_port", lambda: 43123)
    monkeypatch.setattr(
        launcher,
        "serve_browser_home",
        lambda port=None: (SimpleNamespace(), 41000, "http://127.0.0.1:41000/index.html"),
    )

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        return SimpleNamespace(pid=999)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = launcher.launch_sophyane_browser(
        open_home=True,
        start_apis=False,
        enable_cdp=True,
    )

    args = captured["args"]
    assert "--remote-debugging-address=127.0.0.1" in args
    assert "--remote-debugging-port=43123" in args
    assert result["cdp"]["enabled"] is True
    assert result["cdp"]["port"] == 43123
    assert (tmp_path / "cdp-port").read_text().strip() == "43123"


def test_browser_start_cli_returns_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        browser_cli,
        "launch_sophyane_browser",
        lambda **kwargs: {
            "ok": True,
            "pid": 123,
            "cdp": {"enabled": kwargs.get("enable_cdp", False), "port": 9222},
        },
    )
    rc = browser_cli.main(["start", "--cdp"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["cdp"]["enabled"] is True


def test_endpoint_requires_known_port(monkeypatch) -> None:
    monkeypatch.delenv("SOPHYANE_CDP_PORT", raising=False)
    with pytest.raises(CDPError):
        browser_cli._endpoint("127.0.0.1", 0)


def test_explicit_endpoint_port() -> None:
    endpoint = browser_cli._endpoint("127.0.0.1", 9222)
    assert isinstance(endpoint, CDPEndpoint)
    assert endpoint.base_url == "http://127.0.0.1:9222"
