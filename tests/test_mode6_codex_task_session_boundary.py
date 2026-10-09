import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sophyane.providers import codex_cli


def test_mode6_independent_repository_tasks_do_not_resume_previous_codex_thread(
    monkeypatch,
    tmp_path,
):
    """Independent Mode-6 repository tasks must not share Codex conversation state.

    Calls within one repository task may resume its thread. A later independent
    repository task in the same workspace must begin with a fresh Codex thread.
    """

    from sophyane import human_conversation_cli as cli
    from sophyane.providers.human_conversation import HumanConversationProvider

    workspace = tmp_path / "repo"
    workspace.mkdir()

    # Codex requires a trusted git workspace contract, but no real Codex
    # process is executed in this test.
    (workspace / ".git").mkdir()

    state_root = tmp_path / "codex-sessions"
    monkeypatch.setattr(codex_cli, "_STATE_ROOT", state_root)

    commands = []
    started_threads = iter(
        (
            "thread-task-one",
            "thread-task-two",
        )
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
        command = [str(part) for part in command]
        commands.append(command)

        output_index = command.index("--output-last-message") + 1
        output_file = Path(command[output_index])
        output_file.write_text(
            json.dumps(
                {
                    "action": {
                        "type": "run_command",
                        "command": "printf verification",
                    }
                }
            ),
            encoding="utf-8",
        )

        # A fresh Codex invocation emits thread.started. A resume invocation
        # does not need to create a new thread.
        if "resume" not in command:
            thread_id = next(started_threads)
            event = (
                json.dumps(
                    {
                        "type": "thread.started",
                        "thread_id": thread_id,
                    }
                )
                + "\n"
            )
        else:
            event = ""

        return SimpleNamespace(
            returncode=0,
            stdout=event,
            stderr="",
        )

    monkeypatch.setattr(
        codex_cli.subprocess,
        "run",
        fake_run,
    )

    # Keep this test solely about provider-session identity. The adaptive
    # executor is replaced by two provider calls so we can prove:
    #
    #   first call in task -> fresh
    #   second call in same task -> resume
    #
    # without executing any returned action.
    def fake_adaptive_loop(
        *,
        initial_text,
        ask,
        **_kwargs,
    ):
        ask("same task repair")
        return str(initial_text)

    # _execute_repository_request imports run_adaptive_loop from
    # sophyane.adaptive_execution at call time. Patch the authoritative
    # module binding rather than a stale human_conversation_cli alias.
    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_adaptive_loop,
    )

    # Force the repository executor to use the real Mode-6 provider while
    # avoiding unrelated configuration persistence.
    # _execute_repository_request imports create_provider from
    # sophyane.main at call time; patch that authoritative binding.
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: HumanConversationProvider(
            {
                "timeout": 30,
                "temperature": 0,
                "max_tokens": 256,
            }
        ),
    )

    # The executor imports load_config directly from sophyane.config.
    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {},
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    # Avoid availability state affecting which candidate is attempted.
    monkeypatch.setattr(
        "sophyane.providers.human_conversation.provider_block_info",
        lambda _name: None,
        raising=False,
    )

    cli._execute_repository_request(
        "Inspect alpha.py",
        workspace=workspace,
    )

    cli._execute_repository_request(
        "Inspect beta.py",
        workspace=workspace,
    )

    assert len(commands) == 4

    first_task_initial = commands[0]
    first_task_followup = commands[1]
    second_task_initial = commands[2]
    second_task_followup = commands[3]

    assert "resume" not in first_task_initial

    assert "resume" in first_task_followup
    assert "thread-task-one" in first_task_followup

    # Critical boundary assertion:
    #
    # An independent second repository task must NOT resume task one's
    # persisted workspace thread.
    assert "resume" not in second_task_initial

    assert "resume" in second_task_followup
    assert "thread-task-two" in second_task_followup


def test_mode6_repository_task_restores_preexisting_fresh_environment(
    monkeypatch,
    tmp_path,
):
    from sophyane import human_conversation_cli as cli

    observations = []

    class FakeProvider:
        def generate(self, prompt, system_prompt):
            observations.append(os.environ.get("SOPHYANE_CODEX_FRESH"))
            return '{"action":{"type":"run_command","command":"true"}}'

    monkeypatch.setattr("sophyane.main.create_provider", lambda _config: FakeProvider())
    monkeypatch.setattr("sophyane.config.load_config", lambda: {})
    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        lambda *, initial_text, ask, **_kwargs: (ask("same task follow-up") or initial_text),
    )
    monkeypatch.setenv("SOPHYANE_CODEX_FRESH", "caller-value")

    cli._execute_repository_request("Inspect alpha.py", workspace=tmp_path)

    assert observations == ["1", "caller-value"]
    assert os.environ["SOPHYANE_CODEX_FRESH"] == "caller-value"


def test_mode6_repository_task_restores_environment_after_initial_provider_exception(
    monkeypatch,
    tmp_path,
):
    from sophyane import human_conversation_cli as cli

    observations = []

    class RaisingProvider:
        def generate(self, prompt, system_prompt):
            observations.append(os.environ.get("SOPHYANE_CODEX_FRESH"))
            raise RuntimeError("provider failure")

    monkeypatch.setattr("sophyane.main.create_provider", lambda _config: RaisingProvider())
    monkeypatch.setattr("sophyane.config.load_config", lambda: {})
    monkeypatch.setenv("SOPHYANE_CODEX_FRESH", "caller-value")

    with pytest.raises(RuntimeError, match="provider failure"):
        cli._execute_repository_request("Inspect alpha.py", workspace=tmp_path)

    assert observations == ["1"]
    assert os.environ["SOPHYANE_CODEX_FRESH"] == "caller-value"
