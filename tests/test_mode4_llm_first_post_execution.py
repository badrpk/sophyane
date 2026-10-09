from __future__ import annotations

import json

from sophyane import tui_v2
from sophyane.runtime_intent_refinement_patch import (
    install_intent_refinement,
)


def _install_io(
    monkeypatch,
    messages,
    emitted,
):
    iterator = iter(messages)

    def read_prompt(self, prompt="❯ "):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError

    def emit(self, role, text):
        emitted.append(
            (
                str(role),
                str(text),
            )
        )

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


def test_mode4_first_llm_action_enters_structured_execution(
    monkeypatch,
    tmp_path,
):
    """
    Mode 4 contract:

        genuine user request
            -> selected LLM first
            -> existing structured execution runtime
            -> verified final result

    The original request must never be consumed first by deterministic
    dispatch.
    """

    original = "make yring.py"

    first_action = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "yring.py",
                "content": "print('Hello, World!')\n",
            }
        }
    )

    provider_calls = []
    dispatch_calls = []
    structured_calls = []
    emitted = []

    def provider(message):
        provider_calls.append(
            str(message)
        )

        assert len(provider_calls) == 1

        # The first semantic interface receives the untouched user request.
        assert str(message) == original

        return first_action

    def dispatch(message):
        dispatch_calls.append(
            str(message)
        )

        raise AssertionError(
            "deterministic dispatch must not consume "
            "the original Mode-4 request before LLM"
        )

    def structured_loop(
        *,
        initial_text,
        original_request,
        ask,
        workspace,
        max_steps,
    ):
        structured_calls.append(
            {
                "initial_text": str(initial_text),
                "original_request": str(original_request),
                "workspace": workspace,
                "max_steps": max_steps,
            }
        )

        assert json.loads(
            str(initial_text)
        ) == json.loads(first_action)

        assert original_request == original

        return (
            "Created and verified yring.py.\n\n"
            "Path: "
            + str(tmp_path / "yring.py")
        )

    _install_io(
        monkeypatch,
        [original],
        emitted,
    )

    monkeypatch.setattr(
        tui_v2,
        "run_structured_loop",
        structured_loop,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
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

    app.active_workspace = tmp_path.resolve()

    assert app.run() == 0

    assert provider_calls == [
        original,
    ]

    assert dispatch_calls == []

    assert len(structured_calls) == 1

    assert structured_calls[0][
        "original_request"
    ] == original

    assert any(
        role == "Sophyane"
        and "Created and verified yring.py." in text
        for role, text in emitted
    )


def test_mode4_plain_llm_chat_remains_terminal(
    monkeypatch,
    tmp_path,
):
    """
    A normal non-action LLM response must remain an ordinary chat answer
    and must not be forced through repository execution.
    """

    original = "explain dependency injection simply"

    provider_calls = []
    structured_calls = []
    emitted = []

    def provider(message):
        provider_calls.append(
            str(message)
        )

        return (
            "Dependency injection means giving an object "
            "the dependencies it needs from outside."
        )

    def structured_loop(**kwargs):
        structured_calls.append(
            kwargs
        )

        raise AssertionError(
            "plain chat must not enter structured execution"
        )

    _install_io(
        monkeypatch,
        [original],
        emitted,
    )

    monkeypatch.setattr(
        tui_v2,
        "run_structured_loop",
        structured_loop,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "codex_cli",
            "model": "codex-default",
        },
        ask=provider,
        handle_internal=lambda command, current: (
            "",
            current,
        ),
        dispatch_user_request=None,
    )

    app.active_workspace = tmp_path.resolve()

    assert app.run() == 0

    assert provider_calls == [
        original,
    ]

    assert structured_calls == []

    assert any(
        role == "Sophyane"
        and "Dependency injection" in text
        for role, text in emitted
    )


def test_mode4_nifdu_first_action_enters_structured_execution(
    monkeypatch,
    tmp_path,
):
    """The same post-LLM execution contract applies to NIFDU Mode 4."""

    original = "make hello.py"

    first_action = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "hello.py",
                "content": "print('hello')\n",
            }
        }
    )

    events = []
    emitted = []

    def provider(message):
        events.append(
            (
                "llm",
                str(message),
            )
        )

        return first_action

    def dispatch(message):
        events.append(
            (
                "dispatch",
                str(message),
            )
        )

        raise AssertionError(
            "NIFDU deterministic dispatch ran before LLM"
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
            (
                "structured",
                str(original_request),
            )
        )

        assert json.loads(
            str(initial_text)
        ) == json.loads(first_action)

        return "NIFDU structured execution complete"

    _install_io(
        monkeypatch,
        [original],
        emitted,
    )

    monkeypatch.setattr(
        tui_v2,
        "run_structured_loop",
        structured_loop,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "nifdu_browser",
            "model": "browser",
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
        (
            "llm",
            original,
        ),
        (
            "structured",
            original,
        ),
    ]

    assert any(
        role == "Sophyane"
        and text == "NIFDU structured execution complete"
        for role, text in emitted
    )


def test_mode4_browser_software_prose_first_response_enters_adaptive_runtime(
    monkeypatch,
    tmp_path,
):
    """
    A Mode-4 browser/software request still enters the existing adaptive
    browser runtime when the mandatory first LLM response is ordinary prose.

    The LLM remains the first semantic interface.
    """

    original = "make snake game"
    first_response = (
        "Sure — I can make a Snake game for you. "
        "What platform do you want?"
    )

    provider_calls = []
    structured_calls = []
    emitted = []

    def provider(message):
        provider_calls.append(str(message))
        assert len(provider_calls) == 1
        assert str(message) == original
        return first_response

    def structured_loop(
        *,
        initial_text,
        original_request,
        ask,
        workspace,
        max_steps,
    ):
        structured_calls.append(
            {
                "initial_text": str(initial_text),
                "original_request": str(original_request),
                "workspace": workspace,
                "max_steps": max_steps,
            }
        )

        assert initial_text == first_response
        assert original_request == original

        return (
            "Updated and opened the provider-generated "
            "browser project."
        )

    _install_io(
        monkeypatch,
        [original],
        emitted,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setattr(
        tui_v2,
        "run_structured_loop",
        structured_loop,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "nifdu_browser",
            "model": "browser",
        },
        ask=provider,
        handle_internal=lambda command, current: (
            "",
            current,
        ),
        dispatch_user_request=None,
    )

    app.active_workspace = tmp_path.resolve()

    assert tui_v2._is_explicit_mode4_external_session() is True
    assert tui_v2._browser_request(original) is True

    assert app.run() == 0

    assert provider_calls == [original]
    assert len(structured_calls) == 1
    assert (
        structured_calls[0]["original_request"]
        == original
    )

    assert any(
        role == "Sophyane"
        and "opened" in text
        for role, text in emitted
    )
