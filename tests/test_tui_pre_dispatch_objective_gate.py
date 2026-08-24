from pathlib import Path


TUI = Path(
    "src/sophyane/tui_v2.py"
)


def test_one_authoritative_pre_dispatch_gate() -> None:
    text = TUI.read_text()

    assert (
        text.count(
            "SOPHYANE_PRE_DISPATCH_OBJECTIVE_GATE"
        )
        == 1
    )

    assert (
        "SOPHYANE_PRE_PROVIDER_OBJECTIVE_GATE"
        not in text
    )

    assert (
        "SOPHYANE_RAW_PREFLIGHT"
        not in text
    )


def test_gate_is_after_user_echo() -> None:
    text = TUI.read_text()

    assert (
        text.find(
            'self.emit("You", message)'
        )
        <
        text.find(
            "SOPHYANE_PRE_DISPATCH_OBJECTIVE_GATE"
        )
    )


def test_gate_precedes_dispatch_user_request() -> None:
    text = TUI.read_text()

    assert (
        text.find(
            "SOPHYANE_PRE_DISPATCH_OBJECTIVE_GATE"
        )
        <
        text.find(
            "self.dispatch_user_request(message)"
        )
    )


def test_gate_precedes_first_provider_call() -> None:
    text = TUI.read_text()

    assert (
        text.find(
            "SOPHYANE_PRE_DISPATCH_OBJECTIVE_GATE"
        )
        <
        text.find(
            "self.call_provider("
        )
    )


def test_handled_preflight_terminates_iteration() -> None:
    text = TUI.read_text()

    start = text.index(
        "SOPHYANE_PRE_DISPATCH_OBJECTIVE_GATE"
    )

    end = text.index(
        "self.dispatch_user_request(message)"
    )

    section = text[
        start:end
    ]

    assert (
        "preflight_original_request("
        in section
    )

    assert (
        "if preflight_reply is not None:"
        in section
    )

    assert (
        "continue"
        in section
    )
