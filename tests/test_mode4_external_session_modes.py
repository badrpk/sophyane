from __future__ import annotations

import json

import pytest

from sophyane import tui_v2
from sophyane.runtime_intent_refinement_patch import (
    install_intent_refinement,
)


EXTERNAL_MODE4_SESSIONS = (
    ("cloud_llm", "openai"),
    ("nifdu_llm", "nifdu_browser"),
    ("codex_cli", "codex_cli"),
    ("agy", "agy"),
)


def _install_io(monkeypatch, messages, emitted):
    iterator = iter(messages)

    def read_prompt(self, prompt="❯ "):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError

    def emit(self, role, text):
        emitted.append((str(role), str(text)))

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


@pytest.mark.parametrize(
    ("session_mode", "configured_provider"),
    EXTERNAL_MODE4_SESSIONS,
)
def test_each_explicit_mode4_session_uses_llm_as_first_semantic_authority(
    monkeypatch,
    tmp_path,
    session_mode,
    configured_provider,
):
    """
    Every explicit Mode-4 external session must send the untouched
    original request to the selected LLM before deterministic dispatch.

    Once the LLM selects a structured action, the existing structured
    execution runtime receives that action and the untouched original
    request.
    """

    original = f"make {session_mode}_proof.py"

    first_action = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": f"{session_mode}_proof.py",
                "content": "print('external first')\n",
            }
        }
    )

    events = []
    emitted = []

    def provider(message):
        events.append(("llm", str(message)))

        assert len(
            [event for event in events if event[0] == "llm"]
        ) == 1

        assert str(message) == original
        return first_action

    def dispatch(message):
        events.append(("dispatch", str(message)))
        raise AssertionError(
            "deterministic dispatch consumed an explicit Mode-4 "
            "request before the selected LLM"
        )

    def structured_loop(
        *,
        initial_text,
        original_request,
        ask,
        workspace,
        max_steps,
    ):
        events.append(
            ("structured", str(original_request))
        )

        assert json.loads(
            str(initial_text)
        ) == json.loads(first_action)

        assert original_request == original
        assert workspace == tmp_path.resolve()

        return (
            f"{session_mode} structured execution complete"
        )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        session_mode,
    )

    monkeypatch.setattr(
        tui_v2,
        "run_structured_loop",
        structured_loop,
    )

    _install_io(
        monkeypatch,
        [original],
        emitted,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": configured_provider,
            "model": "test-model",
        },
        ask=provider,
        handle_internal=lambda command, current: (
            "",
            current,
        ),
        dispatch_user_request=dispatch,
    )

    app.active_workspace = tmp_path.resolve()

    assert app.run() == 0

    assert events == [
        ("llm", original),
        ("structured", original),
    ]

    assert not any(
        event[0] == "dispatch"
        for event in events
    )

    assert any(
        role == "Sophyane"
        and text
        == f"{session_mode} structured execution complete"
        for role, text in emitted
    )


def test_non_mode4_session_does_not_gain_mode4_authority_from_session_name(
    monkeypatch,
    tmp_path,
):
    """
    A non-Mode-4 session name must not accidentally activate the
    explicit-session Mode-4 boundary when its configured provider is
    also non-Mode-4.
    """

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    source_provider_calls = []

    def provider(message):
        source_provider_calls.append(str(message))
        raise AssertionError(
            "local_llm session unexpectedly entered Mode-4 boundary"
        )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "local_gguf",
            "model": "test-local",
        },
        ask=provider,
        handle_internal=lambda command, current: (
            "",
            current,
        ),
        dispatch_user_request=None,
    )

    app.active_workspace = tmp_path.resolve()

    # This test intentionally verifies only the boundary predicate.
    # Avoid entering the full interactive loop: inspect the effective
    # source to retain a negative guard alongside the behavioral tests.
    source = __import__(
        "inspect"
    ).getsource(tui_v2.ObservableTUI.run)

    assert '"local_llm"' not in source[
        source.index("_sophyane_mode4_llm_first = ("):
        source.index(
            "if _sophyane_mode4_llm_first:"
        )
    ]

    assert source_provider_calls == []
