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


def test_effective_runtime_run_falls_through_when_dispatch_returns_none(
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

            # Dispatcher contract:
            # None means "not handled; continue legacy routing".
            # A response object means "handled; render and stop".
            return None

    class StopAfterFallthrough(Exception):
        pass

    def refinement(*args, **kwargs):
        events.append(
            ("refinement", args[1])
        )
        raise StopAfterFallthrough

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
        effective_run(FakeTUI())
    except StopAfterFallthrough:
        pass
    else:
        raise AssertionError(
            "expected refinement fallthrough"
        )

    assert events.index(
        ("dispatch", "ordinary chat request")
    ) < events.index(
        ("refinement", "ordinary chat request")
    )
