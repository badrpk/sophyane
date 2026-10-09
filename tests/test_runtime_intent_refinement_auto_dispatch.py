from __future__ import annotations

import inspect

import sophyane.tui_v2 as tui_v2
import sophyane.runtime_intent_refinement_patch as patch


def test_effective_runtime_run_honors_auto_dispatch_before_refinement(
    monkeypatch,
):
    # Install the runtime monkeypatch exactly as production does.
    patch.install_intent_refinement()

    source = inspect.getsource(
        tui_v2.ObservableTUI.run
    )

    assert (
        "SOPHYANE_AUTO_EFFECTIVE_TUI_AUTHORITY_V1"
        in source
    )

    assert (
        source.index("dispatch_user_request")
        < source.index("_confirm_refinement")
    )

    events: list[tuple[str, object]] = []

    class FakeTUI:
        active_workspace = None
        active_request = ""
        project_requirements = []
        history = []
        trace = False
        config = {}

        def __init__(self):
            self.messages = iter(
                [
                    "Repair the repository after a pytest failure.",
                    "exit",
                ]
            )

        def read_prompt(self, prompt):
            return next(self.messages)

        def emit(self, role, text):
            events.append(
                ("emit", (role, text))
            )

        def dispatch_user_request(self, message):
            events.append(
                ("dispatch", message)
            )

            class Response:
                text = "AUTO RESULT"

            return Response()

        def call_provider(self, *args, **kwargs):
            raise AssertionError(
                "provider must be unreachable after "
                "handled Auto dispatch"
            )

    monkeypatch.setattr(
        patch,
        "_confirm_refinement",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "intent refinement must be unreachable "
                "after handled Auto dispatch"
            )
        ),
    )

    # The installed function only requires the object protocol;
    # constructing ObservableTUI itself would pull in unrelated
    # production initialization.
    effective_run = tui_v2.ObservableTUI.run

    result = effective_run(FakeTUI())

    assert result == 0

    assert (
        "dispatch",
        "Repair the repository after a pytest failure.",
    ) in events

    assert (
        "emit",
        (
            "Sophyane",
            "AUTO RESULT",
        ),
    ) in events


def test_effective_runtime_dispatch_none_uses_direct_chat_without_refinement(
    monkeypatch,
):
    patch.install_intent_refinement()

    events: list[tuple[str, object]] = []

    class FakeTUI:
        active_workspace = None
        active_request = ""
        project_requirements = []
        history = []
        trace = False
        config = {}

        def __init__(self):
            self.messages = iter(
                [
                    "ordinary chat request",
                    "exit",
                ]
            )

        def read_prompt(self, prompt):
            return next(self.messages)

        def emit(self, role, text):
            events.append(
                ("emit", (role, text))
            )

        def dispatch_user_request(self, message):
            events.append(
                ("dispatch", message)
            )
            return None

        def _context_prompt(
            self,
            message,
            *,
            continuing,
        ):
            events.append(
                (
                    "context",
                    (
                        message,
                        continuing,
                    ),
                )
            )
            return message

        def progress(self, message):
            events.append(
                ("progress", message)
            )

        def call_provider(self, message):
            events.append(
                ("provider", message)
            )

            class Response:
                text = "DIRECT CHAT RESULT"

            return Response()

    monkeypatch.setattr(
        tui_v2,
        "_simple_chat_reply",
        lambda message: None,
    )

    monkeypatch.setattr(
        tui_v2,
        "_render_nonexecuting_response",
        lambda text: text,
    )

    monkeypatch.setattr(
        tui_v2,
        "_explicit_new_benchmark",
        lambda message: False,
    )

    monkeypatch.setattr(
        patch,
        "_confirm_refinement",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "ordinary direct chat must bypass "
                "intent refinement after dispatch(None)"
            )
        ),
    )

    effective_run = tui_v2.ObservableTUI.run

    result = effective_run(
        FakeTUI()
    )

    assert result == 0

    assert (
        "dispatch",
        "ordinary chat request",
    ) in events

    assert any(
        event[0] == "context"
        and event[1][0]
        == "ordinary chat request"
        for event in events
    )

    assert any(
        event[0] == "provider"
        and (
            "Answer directly. No JSON or tool action."
            in event[1]
        )
        for event in events
    )

    assert (
        "emit",
        (
            "Sophyane",
            "DIRECT CHAT RESULT",
        ),
    ) in events


def test_effective_runtime_execution_request_still_reaches_refinement(
    monkeypatch,
):
    patch.install_intent_refinement()

    events: list[tuple[str, object]] = []

    class FakeTUI:
        active_workspace = None
        active_request = ""
        project_requirements = []
        history = []
        trace = False
        config = {}

        def __init__(self):
            self.messages = iter(
                [
                    "Repair the repository after a pytest failure.",
                ]
            )

        def read_prompt(self, prompt):
            return next(self.messages)

        def emit(self, role, text):
            events.append(
                ("emit", (role, text))
            )

        def dispatch_user_request(self, message):
            events.append(
                ("dispatch", message)
            )
            return None

    class StopAtRefinement(Exception):
        pass

    def refinement(
        _self,
        message,
        *,
        has_project,
        tui_v2,
    ):
        events.append(
            (
                "refinement",
                (
                    message,
                    has_project,
                ),
            )
        )
        raise StopAtRefinement

    monkeypatch.setattr(
        tui_v2,
        "_simple_chat_reply",
        lambda message: None,
    )

    monkeypatch.setattr(
        patch,
        "_confirm_refinement",
        refinement,
    )

    effective_run = tui_v2.ObservableTUI.run

    try:
        effective_run(
            FakeTUI()
        )
    except StopAtRefinement:
        pass
    else:
        raise AssertionError(
            "execution request must retain "
            "intent-refinement authority"
        )

    dispatch_event = (
        "dispatch",
        "Repair the repository after a pytest failure.",
    )

    refinement_event = (
        "refinement",
        (
            "Repair the repository after a pytest failure.",
            False,
        ),
    )

    assert dispatch_event in events
    assert refinement_event in events

    assert (
        events.index(dispatch_event)
        < events.index(refinement_event)
    )



def test_effective_runtime_reads_newly_created_file_without_provider(
    monkeypatch,
    tmp_path,
):
    patch.install_intent_refinement()

    events: list[tuple[str, object]] = []

    target = tmp_path / "yuyu.py"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    class FakeTUI:
        active_workspace = None
        active_request = ""
        project_requirements = []
        history = []
        trace = False
        config = {}
        small_local = True

        def __init__(self):
            self.messages = iter(
                [
                    "make file yuyu.py",
                    "what is content of yuyu.py?",
                    "exit",
                ]
            )

        def read_prompt(self, prompt):
            return next(self.messages)

        def emit(self, role, text):
            events.append(
                ("emit", (role, text))
            )

        def dispatch_user_request(self, message):
            events.append(
                ("dispatch", message)
            )
            return None

        def _context_prompt(
            self,
            message,
            *,
            continuing,
        ):
            events.append(
                (
                    "context",
                    (
                        message,
                        continuing,
                    ),
                )
            )
            return message

        def progress(self, message):
            events.append(
                ("progress", message)
            )

        def call_provider(self, message):
            events.append(
                ("provider", message)
            )
            raise AssertionError(
                "provider must be unreachable for grounded "
                "file-content follow-up"
            )

    effective_run = tui_v2.ObservableTUI.run

    result = effective_run(
        FakeTUI()
    )

    assert result == 0
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == ""

    expected_create = (
        "Created yuyu.py directly through Sophyane's "
        "guarded filesystem authority.\n\n"
        f"Path: {target}"
    )

    expected_read = (
        f"Contents of {target}:\n"
    )

    assert (
        "emit",
        (
            "Sophyane",
            expected_create,
        ),
    ) in events

    provider_events = [
        event
        for event in events
        if event[0] == "provider"
    ]

    direct_response_events = [
        event
        for event in events
        if event
        == (
            "progress",
            "Getting direct response",
        )
    ]

    assert (
        "emit",
        (
            "Sophyane",
            expected_read,
        ),
    ) in events, (
        "grounded file-content follow-up was not emitted; "
        f"provider_events={provider_events!r}; "
        f"direct_response_events={direct_response_events!r}"
    )

    assert not provider_events, (
        "provider must be unreachable for grounded "
        "file-content follow-up; "
        f"observed={provider_events!r}"
    )

    assert not direct_response_events, (
        "grounded file-content follow-up must not enter "
        "generic direct-response routing"
    )


# SOPHYANE_MODE4_ACTIVE_FILE_CONTINUITY_SHARP_RED_V1

def test_effective_runtime_remembers_llm_created_file_for_its_content(
    tmp_path,
    monkeypatch,
) -> None:
    """
    Mode 4 preserves active-file continuity without violating LLM-first
    authority.

    First request:
        user -> LLM -> structured execution -> active-file state

    Follow-up:
        user -> LLM first

    The grounded file must never bypass the selected LLM.
    """
    import json

    from sophyane import tui_v2
    from sophyane.runtime_intent_refinement_patch import (
        install_intent_refinement,
    )

    target = tmp_path / "yring2.py"

    create_action = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "yring2.py",
                "content": "print('Hello, World!')\n",
            }
        }
    )

    messages = iter(
        [
            "make yring2.py",
            "what is its content",
        ]
    )

    emitted = []
    provider_calls = []
    dispatch_calls = []
    structured_calls = []

    def read_prompt(self, prompt="❯ "):
        try:
            return next(messages)
        except StopIteration:
            raise EOFError

    def emit(self, role, text):
        emitted.append(
            (
                str(role),
                str(text),
            )
        )

    def provider(message):
        provider_calls.append(
            str(message)
        )

        if len(provider_calls) == 1:
            assert provider_calls[0] == "make yring2.py"
            return create_action

        if len(provider_calls) == 2:
            second = provider_calls[1]

            # The genuine follow-up still reaches the selected LLM first.
            # Sophyane may ground that provider call with remembered active-file
            # context. Grounding must never become a deterministic/local answer
            # that consumes the semantic request before the selected LLM.
            assert second.startswith("what is its content")
            assert "[Sophyane grounded runtime context]" in second
            assert "Active file:" in second
            assert "yring2.py" in second
            assert "Contents:" in second
            assert "print('Hello, World!')" in second

            return (
                "The active file is yring2.py."
            )

        raise AssertionError(
            "unexpected additional provider call"
        )

    def dispatch(message):
        dispatch_calls.append(
            str(message)
        )

        raise AssertionError(
            "Mode 4 deterministic dispatch must not consume "
            "either genuine user request before the LLM"
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
            (
                str(initial_text),
                str(original_request),
                workspace,
                max_steps,
            )
        )

        assert json.loads(
            str(initial_text)
        ) == json.loads(create_action)

        assert original_request == "make yring2.py"

        target.write_text(
            "print('Hello, World!')\n",
            encoding="utf-8",
        )

        return (
            "Created and verified yring2.py.\n\n"
            f"Path: {target}"
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

    monkeypatch.setattr(
        tui_v2,
        "run_structured_loop",
        structured_loop,
    )

    install_intent_refinement()

    tui = tui_v2.ObservableTUI(
        config={
            "provider": "codex_cli",
            "model": "codex-default",
        },
        ask=provider,
        handle_internal=lambda command, config: (
            "",
            config,
        ),
        dispatch_user_request=dispatch,
    )

    tui.active_workspace = tmp_path.resolve()

    assert tui.run() == 0

    assert len(provider_calls) == 2
    assert provider_calls[0] == "make yring2.py"

    second = provider_calls[1]
    assert second.startswith("what is its content")
    assert "[Sophyane grounded runtime context]" in second
    assert "Active file:" in second
    assert "yring2.py" in second
    assert "Contents:" in second
    assert "print('Hello, World!')" in second

    assert dispatch_calls == []

    assert len(structured_calls) == 1

    assert target.exists()

    assert target.read_text(
        encoding="utf-8"
    ) == "print('Hello, World!')\n"

    assert getattr(
        tui,
        "_last_deterministic_file",
        None,
    ) == target

    assert tui.active_workspace == tmp_path.resolve()

    assert any(
        role == "Sophyane"
        and "Created and verified yring2.py." in text
        for role, text in emitted
    )

    assert any(
        role == "Sophyane"
        and text == "The active file is yring2.py."
        for role, text in emitted
    )
