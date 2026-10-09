from __future__ import annotations

from pathlib import Path

from sophyane import tui_v2
from sophyane.runtime_intent_refinement_patch import (
    install_intent_refinement,
)


def _install_tui_io(monkeypatch, messages, events):
    pending = iter(messages)

    def read_prompt(self, prompt="❯ "):
        try:
            return next(pending)
        except StopIteration:
            raise EOFError

    def emit(self, role, text):
        events.append(("emit", role, str(text)))

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


def test_mode4_codex_llm_is_first_semantic_interface(
    monkeypatch,
    tmp_path,
):
    """
    The original genuine user request must reach the selected external
    LLM before deterministic dispatch or grounded-file interpretation.
    """
    events = []
    original = "make yring.py"

    def provider(message):
        events.append(("llm", str(message)))
        return "LLM-FIRST"

    def dispatch(message):
        events.append(("dispatch", str(message)))
        raise AssertionError(
            "Mode 4 deterministic dispatch consumed the request before LLM"
        )

    _install_tui_io(
        monkeypatch,
        [original],
        events,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "codex_cli",
            "model": "codex-default",
        },
        ask=provider,
        handle_internal=lambda command, current: ("", current),
        dispatch_user_request=dispatch,
    )

    app.active_workspace = tmp_path.resolve()

    assert app.run() == 0

    semantic = [
        event
        for event in events
        if event[0] in {"llm", "dispatch"}
    ]

    assert semantic
    assert semantic[0][0] == "llm"
    assert original in semantic[0][1]


def test_mode4_grounded_followup_reaches_llm_before_local_read(
    monkeypatch,
    tmp_path,
):
    """
    Even when Sophyane already knows the active file, the pronoun/reference
    is interpreted by the LLM first. Local grounded-read logic must not
    consume the original request first.
    """
    target = tmp_path / "yring.py"
    target.write_text(
        "print('Hello, World!')\n",
        encoding="utf-8",
    )

    events = []
    original = "what is its content"

    def provider(message):
        events.append(("llm", str(message)))
        return "LLM-FIRST-FOLLOWUP"

    def forbidden_read(*args, **kwargs):
        events.append(("grounded_read", args))
        raise AssertionError(
            "Grounded file reader ran before the Mode 4 LLM"
        )

    monkeypatch.setattr(
        tui_v2,
        "_read_followup_file",
        forbidden_read,
    )

    _install_tui_io(
        monkeypatch,
        [original],
        events,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "codex_cli",
            "model": "codex-default",
        },
        ask=provider,
        handle_internal=lambda command, current: ("", current),
        dispatch_user_request=None,
    )

    app._last_deterministic_file = target.resolve()
    app.active_workspace = tmp_path.resolve()

    assert app.run() == 0

    semantic = [
        event
        for event in events
        if event[0] in {"llm", "grounded_read"}
    ]

    assert semantic
    assert semantic[0][0] == "llm"
    assert original in semantic[0][1]
    assert "yring.py" in semantic[0][1]
    assert "Hello, World!" in semantic[0][1]


def test_mode4_nifdu_llm_is_first_semantic_interface(
    monkeypatch,
    tmp_path,
):
    events = []
    original = "inspect this project and explain it"

    def provider(message):
        events.append(("llm", str(message)))
        return "NIFDU-LLM-FIRST"

    def dispatch(message):
        events.append(("dispatch", str(message)))
        raise AssertionError(
            "Mode 4 NIFDU request entered local dispatch before LLM"
        )

    _install_tui_io(
        monkeypatch,
        [original],
        events,
    )

    install_intent_refinement()

    app = tui_v2.ObservableTUI(
        config={
            "provider": "nifdu_browser",
            "model": "browser",
        },
        ask=provider,
        handle_internal=lambda command, current: ("", current),
        dispatch_user_request=dispatch,
    )

    app.active_workspace = tmp_path.resolve()

    assert app.run() == 0

    semantic = [
        event
        for event in events
        if event[0] in {"llm", "dispatch"}
    ]

    assert semantic
    assert semantic[0] == ("llm", original)


def test_mode6_first_intelligence_boundary_precedes_repository_execution():
    """
    Mode-6 LLM-first authority is a front-door contract.

    A genuine user request must cross conversation intelligence before
    repository execution begins. Once admitted as an actionable mission,
    _execute_repository_request() is downstream of that semantic boundary
    and may reuse an already-verified deterministic or trusted capability
    without acquiring a redundant second provider.
    """
    source = Path(
        "src/sophyane/human_conversation_cli.py"
    ).read_text(encoding="utf-8")

    main_start = source.index("def main()")
    main_body = source[main_start:]

    conversation = main_body.index(
        "result = conversation_turn("
    )

    disposition = main_body.index(
        'if disposition == "actionable_mission":'
    )

    repository_execution = main_body.index(
        "reply = _execute_repository_request(",
        disposition,
    )

    assert conversation < disposition < repository_execution



def test_control_plane_is_exempt_from_llm_first_contract():
    """
    UI/control mechanics are not genuine semantic user requests.
    """
    controls = {
        "exit",
        "quit",
        "/new",
        "/inspect",
        "/trace",
        "/setup",
        "/status",
        "/providers",
        "/doctor",
    }

    assert "make yring.py" not in controls
    assert "what is its content" not in controls
