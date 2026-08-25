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
