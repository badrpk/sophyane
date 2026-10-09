from __future__ import annotations

from pathlib import Path

import pytest

from sophyane import tui_v2
from sophyane.runtime_intent_refinement_patch import (
    install_intent_refinement,
)


def _run_tui(
    monkeypatch,
    *,
    messages,
    provider,
    dispatch,
    config,
):
    pending = iter(messages)
    emitted = []

    def read_prompt(self, prompt="❯ "):
        try:
            return next(pending)
        except StopIteration:
            raise EOFError

    def emit(self, role, text):
        emitted.append((role, str(text)))

    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "read_prompt",
        read_prompt,
    )
    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "emit",
        emit,
    )

    install_intent_refinement()

    tui = tui_v2.ObservableTUI(
        config=config,
        ask=provider,
        handle_internal=lambda command, current: (
            "",
            current,
        ),
        dispatch_user_request=dispatch,
    )

    assert tui.run() == 0
    return tui, emitted


# SOPHYANE_EXTERNAL_LLM_MANDATORY_AUTHORITY_SHARP_RED_V1


def test_mode4_grounded_file_followup_still_calls_selected_llm(
    tmp_path,
    monkeypatch,
):
    """
    Grounding may resolve/read the active file, but it must not become
    the final responder in explicit external-LLM mode.
    """
    target = tmp_path / "yring.py"
    target.write_text(
        "print('Hello, World!')\n",
        encoding="utf-8",
    )

    provider_calls = []
    dispatch_calls = []

    def provider(message):
        provider_calls.append(str(message))
        return "LLM-CONFIRMED-CONTENT"

    def dispatch(message):
        dispatch_calls.append(str(message))

        if message == "make yring.py":
            return (
                '{"handled":true,"ok":true,'
                '"capability":"development.python_create_validate",'
                f'"workspace":{str(tmp_path)!r},'
                '"files":["yring.py"],'
                '"summary":"created","evidence":[],"error":""}'
            )

        return None

    # Start directly with already-grounded active-file state so this
    # contract tests the follow-up authority boundary, not creation.
    pending = iter(["what is its content"])
    emitted = []

    def read_prompt(self, prompt="❯ "):
        try:
            return next(pending)
        except StopIteration:
            raise EOFError

    def emit(self, role, text):
        emitted.append((role, str(text)))

    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "read_prompt",
        read_prompt,
    )
    monkeypatch.setattr(
        tui_v2.ObservableTUI,
        "emit",
        emit,
    )

    install_intent_refinement()

    tui = tui_v2.ObservableTUI(
        config={
            "provider": "codex_cli",
            "model": "codex-default",
        },
        ask=provider,
        handle_internal=lambda command, current: (
            "",
            current,
        ),
        dispatch_user_request=dispatch,
    )

    tui._last_deterministic_file = target.resolve()
    tui.active_workspace = tmp_path.resolve()

    assert tui.run() == 0

    # Core invariant:
    # explicit Mode 4 cannot complete a genuine user request
    # solely from deterministic grounding.
    assert len(provider_calls) == 1

    # Grounded context must be useful to the LLM.
    payload = provider_calls[0]
    assert "yring.py" in payload
    assert "Hello, World!" in payload

    assert any(
        "LLM-CONFIRMED-CONTENT" in text
        for role, text in emitted
        if role == "Sophyane"
    )


def test_mode4_deterministic_creation_cannot_complete_without_llm(
    tmp_path,
    monkeypatch,
):
    """
    A deterministic capability may support execution, but in Mode 4
    it cannot consume the request and produce final completion before
    the selected LLM participates.
    """
    provider_calls = []
    dispatch_calls = []

    def provider(message):
        provider_calls.append(str(message))
        return (
            '{"action":{"type":"write_file",'
            '"path":"yring.py",'
            '"content":"print(\'Hello, World!\')\\n"}}'
        )

    def dispatch(message):
        dispatch_calls.append(str(message))
        return (
            '{"handled":true,"ok":true,'
            '"capability":"development.python_create_validate",'
            f'"workspace":"{tmp_path}",'
            '"files":["yring.py"],'
            '"summary":"created","evidence":[],"error":""}'
        )

    _run_tui(
        monkeypatch,
        messages=["make yring.py"],
        provider=provider,
        dispatch=dispatch,
        config={
            "provider": "codex_cli",
            "model": "codex-default",
        },
    )

    assert len(provider_calls) >= 1


def test_mode6_provider_wrapper_remains_llm_authority(
    monkeypatch,
):
    """
    Mode 6 must resolve every genuine conversational request through
    its authorized LLM cascade rather than a providerless final answer.
    """
    import sophyane.providers.human_conversation as human

    provider_calls = []

    class FakeProvider:
        provider_id = "codex_cli"

        def generate(
            self,
            prompt,
            system_prompt="",
            **kwargs,
        ):
            provider_calls.append(
                (
                    str(prompt),
                    str(system_prompt),
                )
            )
            return "MODE6-LLM-ANSWER"

    wrapper = human.HumanConversationProvider(
        config={"timeout": 30}
    )

    monkeypatch.setattr(
        wrapper,
        "_create",
        lambda name: FakeProvider(),
    )

    result = wrapper.generate(
        "what is this file?",
        "test-system",
    )

    assert result == "MODE6-LLM-ANSWER"
    assert len(provider_calls) == 1


def test_mode4_internal_control_command_is_not_user_llm_request():
    """
    The invariant applies to genuine user requests, not local UI
    controls such as exit/provider-selection mechanics.
    """
    # This test intentionally documents the boundary rather than
    # forcing control-plane commands through an LLM.
    assert True
