from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import sophyane.providers.codex_cli as codex_cli
import sophyane.startup_policy as startup_policy
import sophyane.tui_v2 as tui
import sophyane.v13_cli as cli
from sophyane.main import create_provider
from sophyane.providers.codex_cli import AntigravityProvider, CodexCliProvider
from sophyane.v13_cli import _execution_session_mode


def _fake_run_factory(calls):
    def fake_run(command, **kwargs):
        calls.append(
            {
                "command": list(command),
                "input": kwargs.get("input"),
                "cwd": kwargs.get("cwd"),
                "timeout": kwargs.get("timeout"),
            }
        )

        output_index = command.index(
            "--output-last-message"
        ) + 1

        Path(command[output_index]).write_text(
            "CODEX_PROVIDER_PASS\n",
            encoding="utf-8",
        )

        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "type": "thread.started",
                "thread_id": "thread-test-123",
            }) + "\n",
            stderr="",
        )

    return fake_run


def test_codex_provider_starts_read_only_session(
    tmp_path,
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        codex_cli,
        "_STATE_ROOT",
        tmp_path / "state",
    )
    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        _fake_run_factory(calls),
    )
    monkeypatch.setenv(
        "SOPHYANE_CODEX_CLI",
        "/usr/bin/codex",
    )

    provider = CodexCliProvider(
        workspace=tmp_path,
        timeout=45,
    )

    assert provider.generate(
        "request",
        "system",
    ) == "CODEX_PROVIDER_PASS"

    command = calls[0]["command"]

    assert command[:2] == [
        "/usr/bin/codex",
        "exec",
    ]
    assert "--sandbox" in command
    assert "read-only" in command
    assert calls[0]["timeout"] == 45


def test_codex_provider_resumes_workspace_session(
    tmp_path,
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        codex_cli,
        "_STATE_ROOT",
        tmp_path / "state",
    )
    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        _fake_run_factory(calls),
    )
    monkeypatch.setenv(
        "SOPHYANE_CODEX_CLI",
        "/usr/bin/codex",
    )

    provider = CodexCliProvider(
        workspace=tmp_path,
    )

    provider.generate("first", "system")
    provider.generate("second", "system")

    resumed = calls[1]["command"]

    assert resumed[:3] == [
        "/usr/bin/codex",
        "exec",
        "resume",
    ]
    assert "thread-test-123" in resumed


def test_create_provider_honors_codex_session(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "codex_cli",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "codex-default",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_TIMEOUT",
        "300",
    )
    monkeypatch.setenv(
        "SOPHYANE_CODEX_CLI",
        "/usr/bin/codex",
    )

    provider = create_provider({})

    assert isinstance(
        provider,
        CodexCliProvider,
    )
    assert provider.timeout == 300


def test_v13_resolves_codex_alias(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex",
    )

    assert (
        _execution_session_mode()
        == "codex_cli"
    )


def test_mode4_menu_contains_ordered_choices():
    text = Path(
        "src/sophyane/startup_policy.py"
    ).read_text(encoding="utf-8")

    api = text.index(
        "1. Cloud API"
    )
    browser = text.index(
        "2. NIFDU Browser"
    )
    codex = text.index(
        "3. Codex CLI"
    )
    agy = text.index(
        "4. Antigravity (AGY)"
    )

    assert api < browser < codex < agy


def _choose_mode4(monkeypatch, intelligence):
    # choose_startup_provider() intentionally writes session policy directly
    # through os.environ. Register every startup-session key with MonkeyPatch
    # first so those production writes cannot escape this test.
    for key in (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_SLI_CONTINUOUS",
        "SOPHYANE_TOPIC_LEARNING",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        "SOPHYANE_DISABLE_LOCAL_FALLBACK",
        "SOPHYANE_ALLOW_CLOUD_LOCAL_RESCUE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_SESSION_MODEL",
        "SOPHYANE_SESSION_TIMEOUT",
    ):
        monkeypatch.setenv(key, "__sophyane_test_unset__")
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(startup_policy, "load_config", lambda: {})
    monkeypatch.setattr(startup_policy, "_load_llm", lambda: {})
    monkeypatch.setattr(startup_policy, "_local_candidate", lambda *_: None)
    monkeypatch.setattr(
        startup_policy, "_configured_clouds", lambda: [("gemini", "Gemini")]
    )
    monkeypatch.setattr(startup_policy, "_cloud_model", lambda *_: "gemini-model")
    monkeypatch.setattr(startup_policy, "save_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(startup_policy.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)
    answers = iter(["4", intelligence])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    return startup_policy.choose_startup_provider()


def test_mode4_antigravity_selection_routes_exact_config(monkeypatch):
    result = _choose_mode4(monkeypatch, "4")

    assert result == {
        "provider": "agy",
        "model": "agy-default",
        "company": "Antigravity (AGY)",
        "timeout": 300,
    }
    assert startup_policy.os.environ["SOPHYANE_SESSION_MODE"] == "agy"
    assert startup_policy.os.environ["SOPHYANE_SESSION_PROVIDER"] == "agy"
    assert startup_policy.os.environ["SOPHYANE_SESSION_MODEL"] == "agy-default"
    assert startup_policy.os.environ["SOPHYANE_SESSION_TIMEOUT"] == "300"


def test_antigravity_provider_uses_discovered_read_only_contract(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)
    monkeypatch.setenv("SOPHYANE_AGY_PROOT", "/usr/bin/proot-distro")
    monkeypatch.setenv("SOPHYANE_AGY_CLI", "/root/.local/bin/agy")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "SUCCESS", "response": "AGY_PASS"}),
            stderr="",
        )

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    provider = AntigravityProvider(workspace=tmp_path, timeout=45)

    assert provider.generate("request", "system") == "AGY_PASS"
    command, kwargs = calls[0]
    assert command[:7] == [
        "/usr/bin/proot-distro", "login", "--work-dir", str(tmp_path),
        "debian", "--", "/root/.local/bin/agy"
    ]
    assert command[7] == "-p"
    assert command[9:] == [
        "--mode", "plan", "--output-format", "json",
        "--print-timeout", "45s", "--sandbox",
    ]
    assert kwargs["timeout"] == 45


def test_create_provider_honors_antigravity_session(monkeypatch):
    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "agy")
    monkeypatch.setenv("SOPHYANE_SESSION_MODEL", "agy-default")
    monkeypatch.setenv("SOPHYANE_SESSION_TIMEOUT", "300")
    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)

    provider = create_provider({})

    assert isinstance(provider, AntigravityProvider)
    assert provider.model == "agy-default"
    assert provider.timeout == 300


def test_antigravity_session_bypasses_race_and_reaches_normal_runtime(
    monkeypatch,
):
    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "agy")
    monkeypatch.setenv("SOPHYANE_SESSION_MODEL", "agy-default")
    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)

    provider_calls = []
    captured = {}

    def fake_generate(self, prompt, system=None):
        provider_calls.append((prompt, system))
        return "AGY downstream response"

    monkeypatch.setattr(AntigravityProvider, "generate", fake_generate)

    import sophyane.agent as agent_module

    class FakeAgent:
        def __init__(self, provider, *_args):
            assert isinstance(provider, AntigravityProvider)
            self.provider = provider

        def ask(self, message):
            return SimpleNamespace(text=self.provider.generate(message))

    monkeypatch.setattr(agent_module, "SophyaneAgent", FakeAgent)
    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("AGY entered adaptive race")
        ),
    )

    def fake_run(self):
        captured["ask"] = self.ask
        captured["dispatch"] = self.dispatch_user_request
        return 0

    monkeypatch.setattr(tui.ObservableTUI, "run", fake_run)

    assert tui.run_observable_tui(config={}) == 0
    assert captured["dispatch"] is None

    response = captured["ask"]("Plan the requested change")

    assert response.text == "AGY downstream response"
    assert provider_calls == [("Plan the requested change", None)]


def test_external_session_dispatch_contract_remains_explicit(monkeypatch):
    for selected, expected in (
        ("agy", "agy"),
        ("codex_cli", "codex_cli"),
        ("nifdu_llm", "nifdu_llm"),
    ):
        monkeypatch.setenv("SOPHYANE_SESSION_MODE", selected)
        assert _execution_session_mode() == expected


def test_mode1_auto_still_uses_adaptive_race(monkeypatch):
    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "race")

    assert _execution_session_mode() == "race"
    assert cli._should_use_adaptive_race() is True


def test_mode4_invalid_external_selection_still_falls_back_to_cloud(monkeypatch):
    result = _choose_mode4(monkeypatch, "invalid")

    assert result["provider"] == "gemini"
    assert result["model"] == "gemini-model"
    assert result["timeout"] == 180
    assert startup_policy.os.environ["SOPHYANE_SESSION_MODE"] == "cloud_llm"


def test_antigravity_failure_reports_real_status(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)
    monkeypatch.setattr(
        codex_cli,
        "agy_command",
        lambda workspace=None: [
            "/usr/bin/proot-distro",
            "login",
            "debian",
            "--",
            "/root/.local/bin/agy",
        ],
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "status": "FAILED",
                "response": "",
                "message": "provider-side diagnostic",
            }),
            stderr="proot warning",
        )

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)

    provider = AntigravityProvider(
        workspace=tmp_path,
        timeout=45,
    )

    import pytest

    with pytest.raises(
        codex_cli.ProviderError,
        match=(
            r"status=FAILED; "
            r"response_present=False; "
            r"diagnostic=provider-side diagnostic"
        ),
    ):
        provider.generate("request", "system")


def test_antigravity_nonzero_exit_preserves_stdout_json_diagnostic(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)
    monkeypatch.setattr(
        codex_cli,
        "agy_command",
        lambda workspace=None: [
            "/usr/bin/proot-distro",
            "login",
            "debian",
            "--",
            "/root/.local/bin/agy",
        ],
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "status": "FAILED",
                "response": "",
                "message": "actual agy failure reason",
            }),
            stderr=(
                "proot warning: can't sanitize binding "
                '"/proc/self/fd/1"'
            ),
        )

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)

    provider = AntigravityProvider(
        workspace=tmp_path,
        timeout=45,
    )

    import pytest

    with pytest.raises(
        codex_cli.ProviderError,
        match="actual agy failure reason",
    ) as error:
        provider.generate("request", "system")

    message = str(error.value)
    assert "agy_status='FAILED'" in message
    assert "response_present=False" in message
    assert "proot warning" in message
