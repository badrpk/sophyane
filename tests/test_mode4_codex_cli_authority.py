from __future__ import annotations
import pytest

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


def test_mode4_menu_contains_exact_transport_families():
    assert startup_policy.mode4_transport_families() == (
        "APIs",
        "NIFDU Browser",
        "Harnesses / CLI",
    )


def _choose_mode4(monkeypatch, *selections):
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
    answers = iter(["4", *selections])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    return startup_policy.choose_startup_provider()


def test_mode4_antigravity_selection_routes_exact_config(monkeypatch):
    result = _choose_mode4(monkeypatch, "3", "2")

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
    monkeypatch.setenv("SOPHYANE_SESSION_PROVIDER", "agy")
    monkeypatch.setenv("SOPHYANE_SESSION_MODEL", "agy-default")

    monkeypatch.setattr(codex_cli, "agy_available", lambda: True)

    provider = create_provider({})

    assert isinstance(provider, AntigravityProvider)
    assert provider.provider_id == "agy"
    assert provider.model == "agy-default"


def test_antigravity_session_bypasses_race_and_reaches_normal_runtime(
    monkeypatch,
):
    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "codex_cli")
    monkeypatch.setenv("SOPHYANE_SESSION_MODEL", "codex-default")

    provider_calls = []
    captured = {}

    def fake_generate(self, prompt, system=None):
        provider_calls.append((prompt, system))
        return "Codex downstream response"

    monkeypatch.setattr(CodexCliProvider, "generate", fake_generate)

    import sophyane.agent as agent_module

    class FakeAgent:
        def __init__(self, provider, *_args):
            assert isinstance(provider, CodexCliProvider)
            self.provider = provider

        def ask(self, message):
            return SimpleNamespace(text=self.provider.generate(message))

    monkeypatch.setattr(agent_module, "SophyaneAgent", FakeAgent)
    monkeypatch.setattr(
        cli,
        "_run_adaptive_race_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Codex entered adaptive race")
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
    assert response.text == "Codex downstream response"
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


def test_mode4_invalid_external_selection_reprompts_without_fallback(monkeypatch):
    result = _choose_mode4(
        monkeypatch,
        "invalid",
        "1",
        "1",
    )

    assert result["provider"] == "gemini"
    assert result["model"] == "gemini-model"
    assert startup_policy.os.environ["SOPHYANE_SESSION_MODE"] == "cloud_llm"
    assert startup_policy.os.environ["SOPHYANE_SESSION_PROVIDER"] == "gemini"


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


# SOPHYANE_CODEX_EXHAUSTED_THREAD_RECOVERY_SHARP_RED_V1

def test_codex_exhausted_resumed_thread_retries_once_fresh(
    tmp_path,
    monkeypatch,
):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    import sophyane.providers.codex_cli as codex_cli

    workspace = tmp_path / "repo"
    workspace.mkdir()

    old_thread = "11111111-1111-1111-1111-111111111111"
    new_thread = "22222222-2222-2222-2222-222222222222"

    monkeypatch.setattr(
        codex_cli,
        "_load_session",
        lambda workspace_arg: old_thread,
    )

    saved = []

    monkeypatch.setattr(
        codex_cli,
        "_save_session",
        lambda workspace_arg, thread_id: saved.append(
            (Path(workspace_arg), thread_id)
        ),
    )

    calls = []

    def fake_run(
        command,
        *,
        input,
        text,
        stdout,
        stderr,
        cwd,
        timeout,
        check,
    ):
        calls.append(list(command))

        output_path = Path(
            command[
                command.index("--output-last-message")
                + 1
            ]
        )

        if len(calls) == 1:
            assert "resume" in command
            assert old_thread in command

            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "Failed to run pre-sampling compact: "
                    "Error running remote compact task: "
                    "Codex ran out of room in the model's "
                    "context window. Start a new thread or "
                    "clear earlier history before retrying. "
                    '"codex_error_info":'
                    '"context_window_exceeded"'
                ),
            )

        assert len(calls) == 2
        assert "resume" not in command
        assert old_thread not in command
        assert "--sandbox" in command
        assert "read-only" in command

        output_path.write_text(
            "fresh-thread-success",
            encoding="utf-8",
        )

        return SimpleNamespace(
            returncode=0,
            stdout=(
                json.dumps(
                    {
                        "type": "thread.started",
                        "thread_id": new_thread,
                    }
                )
                + "\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        fake_run,
    )

    provider = codex_cli.CodexCliProvider(
        workspace=workspace,
    )

    result = provider.generate(
        "what is its content",
        "test-system",
    )

    assert result == "fresh-thread-success"

    assert len(calls) == 2

    assert saved == [
        (workspace.resolve(), new_thread),
    ]


def test_codex_unrelated_resume_failure_never_retries_fresh(
    tmp_path,
    monkeypatch,
):
    from pathlib import Path
    from types import SimpleNamespace

    import pytest
    import sophyane.providers.codex_cli as codex_cli
    from sophyane.providers.base import ProviderError

    workspace = tmp_path / "repo"
    workspace.mkdir()

    old_thread = "33333333-3333-3333-3333-333333333333"

    monkeypatch.setattr(
        codex_cli,
        "_load_session",
        lambda workspace_arg: old_thread,
    )

    saved = []

    monkeypatch.setattr(
        codex_cli,
        "_save_session",
        lambda workspace_arg, thread_id: saved.append(
            (Path(workspace_arg), thread_id)
        ),
    )

    calls = []

    def fake_run(
        command,
        *,
        input,
        text,
        stdout,
        stderr,
        cwd,
        timeout,
        check,
    ):
        calls.append(list(command))

        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="authentication failed",
        )

    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        fake_run,
    )

    provider = codex_cli.CodexCliProvider(
        workspace=workspace,
    )

    with pytest.raises(
        ProviderError,
        match="authentication failed",
    ):
        provider.generate(
            "hello",
            "test-system",
        )

    assert len(calls) == 1
    assert "resume" in calls[0]
    assert old_thread in calls[0]
    assert saved == []


def test_codex_fresh_thread_failure_is_not_recursively_retried(
    tmp_path,
    monkeypatch,
):
    from pathlib import Path
    from types import SimpleNamespace

    import pytest
    import sophyane.providers.codex_cli as codex_cli
    from sophyane.providers.base import ProviderError

    workspace = tmp_path / "repo"
    workspace.mkdir()

    old_thread = "44444444-4444-4444-4444-444444444444"

    monkeypatch.setattr(
        codex_cli,
        "_load_session",
        lambda workspace_arg: old_thread,
    )

    saved = []

    monkeypatch.setattr(
        codex_cli,
        "_save_session",
        lambda workspace_arg, thread_id: saved.append(
            (Path(workspace_arg), thread_id)
        ),
    )

    calls = []

    exhausted = (
        "Failed to run pre-sampling compact: "
        "Codex ran out of room in the model's context window. "
        '"codex_error_info":"context_window_exceeded"'
    )

    def fake_run(
        command,
        *,
        input,
        text,
        stdout,
        stderr,
        cwd,
        timeout,
        check,
    ):
        calls.append(list(command))

        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=exhausted,
        )

    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        fake_run,
    )

    provider = codex_cli.CodexCliProvider(
        workspace=workspace,
    )

    with pytest.raises(
        ProviderError,
        match="context_window_exceeded",
    ):
        provider.generate(
            "hello",
            "test-system",
        )

    # One poisoned resume + exactly one fresh recovery attempt.
    assert len(calls) == 2

    assert "resume" in calls[0]
    assert old_thread in calls[0]

    assert "resume" not in calls[1]

    assert saved == []


def test_codex_short_presampling_compact_resume_retries_once_fresh(
    tmp_path,
    monkeypatch,
):
    """Codex 0.156.1 may expose only the top-level compact failure."""
    import json
    from pathlib import Path
    from types import SimpleNamespace

    import sophyane.providers.codex_cli as codex_cli

    workspace = tmp_path / "repo"
    workspace.mkdir()

    old_thread = "55555555-5555-5555-5555-555555555555"
    new_thread = "66666666-6666-6666-6666-666666666666"

    monkeypatch.setattr(
        codex_cli,
        "_load_session",
        lambda workspace_arg: old_thread,
    )

    saved = []
    monkeypatch.setattr(
        codex_cli,
        "_save_session",
        lambda workspace_arg, thread_id: saved.append(
            (Path(workspace_arg), thread_id)
        ),
    )

    calls = []

    def fake_run(
        command,
        *,
        input,
        text,
        stdout,
        stderr,
        cwd,
        timeout,
        check,
    ):
        calls.append(list(command))

        output_path = Path(
            command[
                command.index("--output-last-message") + 1
            ]
        )

        if len(calls) == 1:
            assert "resume" in command
            assert old_thread in command

            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "2026-09-28T09:01:03.281366Z "
                    "ERROR codex_core::session::turn: "
                    "Failed to run pre-sampling compact"
                ),
            )

        assert len(calls) == 2
        assert "resume" not in command
        assert old_thread not in command
        assert "--sandbox" in command
        assert "read-only" in command

        output_path.write_text(
            "fresh-short-compact-success",
            encoding="utf-8",
        )

        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "thread.started",
                    "thread_id": new_thread,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        fake_run,
    )

    provider = codex_cli.CodexCliProvider(
        workspace=workspace,
    )

    result = provider.generate(
        "hello",
        "test-system",
    )

    assert result == "fresh-short-compact-success"
    assert len(calls) == 2
    assert saved == [(workspace.resolve(), new_thread)]


# SOPHYANE_CODEX_INPUT_TOO_LARGE_RESUME_RECOVERY_V1

def test_codex_input_too_large_resumed_thread_retries_once_fresh(
    tmp_path,
    monkeypatch,
):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    import sophyane.providers.codex_cli as codex_cli

    workspace = tmp_path / "repo"
    workspace.mkdir()

    old_thread = "77777777-7777-7777-7777-777777777777"
    new_thread = "88888888-8888-8888-8888-888888888888"

    monkeypatch.setattr(
        codex_cli,
        "_load_session",
        lambda workspace_arg: old_thread,
    )

    saved = []

    monkeypatch.setattr(
        codex_cli,
        "_save_session",
        lambda workspace_arg, thread_id: saved.append(
            (Path(workspace_arg), thread_id)
        ),
    )

    calls = []

    def fake_run(
        command,
        *,
        input,
        text,
        stdout,
        stderr,
        cwd,
        timeout,
        check,
    ):
        calls.append(list(command))

        output_path = Path(
            command[
                command.index("--output-last-message") + 1
            ]
        )

        if len(calls) == 1:
            assert "resume" in command
            assert old_thread in command

            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "turn/start failed: "
                    "Input exceeds the maximum length of "
                    "1048576 characters. "
                    "input_error_code: input_too_large "
                    "actual_chars: 1283486"
                ),
            )

        assert len(calls) == 2
        assert "resume" not in command
        assert old_thread not in command
        assert "--sandbox" in command
        assert "read-only" in command

        output_path.write_text(
            "fresh-input-size-success",
            encoding="utf-8",
        )

        return SimpleNamespace(
            returncode=0,
            stdout=(
                json.dumps(
                    {
                        "type": "thread.started",
                        "thread_id": new_thread,
                    }
                )
                + "\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        fake_run,
    )

    provider = codex_cli.CodexCliProvider(
        workspace=workspace,
    )

    result = provider.generate(
        "current request remains unchanged",
        "test-system",
    )

    assert result == "fresh-input-size-success"
    assert len(calls) == 2
    assert saved == [
        (workspace.resolve(), new_thread),
    ]
