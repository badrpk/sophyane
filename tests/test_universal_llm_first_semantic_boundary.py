from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sophyane import human_conversation_cli as mode6_cli
from sophyane import runtime_intent_refinement_patch as patch
from sophyane import tui_v2
from sophyane.rsi.authority import Operation


def _mode4_tui(
    monkeypatch,
    *,
    provider_name: str,
    message: str,
    provider,
):
    messages = iter([message])

    def read_prompt(self, prompt="❯ "):
        try:
            return next(messages)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "read_prompt",
        read_prompt,
    )

    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "emit",
        lambda self, role, text: None,
    )

    patch.install_intent_refinement()

    return tui_v2.ObservableTUI(
        config={
            "provider": provider_name,
            "model": "test-model",
        },
        ask=provider,
        handle_internal=lambda command, config: (
            "",
            config,
        ),
        dispatch_user_request=lambda message: None,
    )


def test_mode4_nifdu_grounding_cannot_consume_before_llm(
    tmp_path: Path,
    monkeypatch,
):
    """
    A request that the legacy NIFDU grounding path understands must still
    reach the selected LLM before any grounded semantic interpretation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    target = tmp_path / "grounded.py"
    target.write_text(
        "print('grounded')\n",
        encoding="utf-8",
    )

    events = []

    def provider(message):
        events.append(("provider", str(message)))
        return "LLM_FIRST_OK"

    def forbidden_grounding(*args, **kwargs):
        events.append(("grounding", args[0] if args else None))
        raise AssertionError(
            "NIFDU grounding semantically consumed the request "
            "before the selected LLM"
        )

    monkeypatch.setattr(
        "sophyane.nifdu_guarded_execution."
        "grounded_nifdu_python_file_read",
        forbidden_grounding,
    )

    tui = _mode4_tui(
        monkeypatch,
        provider_name="nifdu_browser",
        message="code of grounded.py",
        provider=provider,
    )

    assert tui.run() == 0

    assert events
    assert events[0] == (
        "provider",
        "code of grounded.py",
    )


def test_mode4_preflight_cannot_consume_before_llm(
    tmp_path: Path,
    monkeypatch,
):
    """
    Objective preflight is semantic policy/routing. In Mode 4 it must be
    downstream of the first selected-LLM turn.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )

    events = []

    def provider(message):
        events.append(("provider", str(message)))
        return "LLM_FIRST_OK"

    def forbidden_preflight(message):
        events.append(("preflight", str(message)))
        raise AssertionError(
            "objective preflight consumed the genuine request "
            "before the selected LLM"
        )

    monkeypatch.setattr(
        "sophyane.objective_preflight.preflight_original_request",
        forbidden_preflight,
    )

    tui = _mode4_tui(
        monkeypatch,
        provider_name="codex_cli",
        message="inspect this project and explain it",
        provider=provider,
    )

    assert tui.run() == 0

    assert events
    assert events[0] == (
        "provider",
        "inspect this project and explain it",
    )


def test_mode4_deterministic_empty_create_cannot_run_before_llm(
    tmp_path: Path,
    monkeypatch,
):
    """
    Even a trivial deterministic write is a genuine semantic request.
    The LLM chooses the action first; Sophyane may execute afterwards.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )

    events = []

    def provider(message):
        events.append(("provider", str(message)))
        return "LLM_FIRST_OK"

    def forbidden_create(*args, **kwargs):
        events.append(("create", args[0] if args else None))
        raise AssertionError(
            "deterministic empty-create consumed the request "
            "before the selected LLM"
        )

    monkeypatch.setattr(
        "sophyane.nifdu_guarded_execution."
        "deterministic_empty_python_create",
        forbidden_create,
    )

    tui = _mode4_tui(
        monkeypatch,
        provider_name="codex_cli",
        message="create a file universal_boundary.py",
        provider=provider,
    )

    assert tui.run() == 0

    assert events
    assert events[0] == (
        "provider",
        "create a file universal_boundary.py",
    )


def test_mode4_control_plane_still_bypasses_llm(
    tmp_path: Path,
    monkeypatch,
):
    """
    /status is control-plane input, not a genuine semantic user request.
    It remains local and must not invoke the LLM.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )

    provider_calls = []
    internal_calls = []
    messages = iter(["/status", "exit"])

    def read_prompt(self, prompt="❯ "):
        return next(messages)

    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "read_prompt",
        read_prompt,
    )

    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "emit",
        lambda self, role, text: None,
    )

    patch.install_intent_refinement()

    tui = tui_v2.ObservableTUI(
        config={
            "provider": "codex_cli",
            "model": "test-model",
        },
        ask=lambda message: provider_calls.append(message),
        handle_internal=lambda command, config: (
            internal_calls.append(command) or "STATUS_OK",
            config,
        ),
        dispatch_user_request=lambda message: None,
    )

    assert tui.run() == 0
    assert provider_calls == []
    assert internal_calls == ["status"]


def test_mode6_original_request_not_classified_before_first_llm(
    monkeypatch,
):
    """
    Strict Mode-6 front-door invariant:

        genuine request -> conversation intelligence -> guarded execution

    Repository capability classification and operation mapping must not
    semantically consume the original request before that first intelligence
    turn. Once intelligence admits the mission, downstream execution may reuse
    an existing verified capability without acquiring a second provider.
    """
    request = "make file mode6_first.py containing exactly FIRST"

    events = []

    def conversation(text, **kwargs):
        events.append(
            (
                "provider",
                str(text),
            )
        )

        return SimpleNamespace(
            reply="route",
            semantic_disposition="actionable_mission",
        )

    def execute(text, **kwargs):
        events.append(
            (
                "execute",
                str(text),
            )
        )

        return mode6_cli._CompletedRepositoryExecution(
            "DONE"
        )

    def forbidden_capability(request_text):
        events.append(
            (
                "capability",
                str(request_text),
            )
        )
        raise AssertionError(
            "repository capability classified the original request "
            "before the first LLM turn"
        )

    def forbidden_operation(request_text):
        events.append(
            (
                "operation",
                str(request_text),
            )
        )
        raise AssertionError(
            "repository operation classified the original request "
            "before the first LLM turn"
        )

    values = iter(
        [
            request,
            "/exit",
        ]
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    monkeypatch.setattr(
        mode6_cli,
        "_read_atomic_submission",
        lambda _prompt: next(values),
    )

    monkeypatch.setattr(
        mode6_cli,
        "conversation_turn",
        conversation,
    )

    monkeypatch.setattr(
        mode6_cli,
        "_execute_repository_request",
        execute,
    )

    monkeypatch.setattr(
        "sophyane.request_classification."
        "classify_repository_capability",
        forbidden_capability,
    )

    monkeypatch.setattr(
        mode6_cli,
        "_repository_operation_for_request",
        forbidden_operation,
    )

    assert mode6_cli.main() == 0

    assert events == [
        (
            "provider",
            request,
        ),
        (
            "execute",
            request,
        ),
    ]


def test_mode6_first_provider_turn_uses_nonsemantic_safe_authority(
    tmp_path: Path,
    monkeypatch,
):
    """
    The initial Mode-6 LLM turn must not require semantic operation
    classification of the user's request merely to select the provider route.

    READ_ONLY_OPERATION is the provider API's existing default and is used
    here only as the non-mutating authority for the first semantic turn.
    """
    request = "modify src/sophyane/example.py"

    seen_operations = []

    class FakeHumanProvider:
        execution_provider_evidence = []
        execution_provider_route_evidence = []
        last_provider = "codex_cli"
        last_provider_route = ("codex_cli[success]",)

        def generate(
            self,
            prompt,
            system_prompt,
            *,
            operation=Operation.READ_ONLY_OPERATION,
        ):
            seen_operations.append(operation)

            return (
                '{"action":{"type":"respond",'
                '"message":"classified downstream"}}'
            )

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: FakeHumanProvider(),
    )

    monkeypatch.setattr(
        "sophyane.main.load_runtime_config",
        lambda: {},
    )

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {},
    )

    monkeypatch.setattr(
        "sophyane.providers.human_conversation."
        "HumanConversationProvider",
        FakeHumanProvider,
    )

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        lambda **kwargs: "DONE",
    )

    mode6_cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    assert seen_operations

    assert seen_operations[0] is Operation.READ_ONLY_OPERATION
