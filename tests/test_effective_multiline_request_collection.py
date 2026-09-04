from pathlib import Path


def test_effective_route_accepts_before_dispatch():
    source = Path("src/sophyane/runtime_intent_refinement_patch.py").read_text(encoding="utf-8")
    run_start = source.index("    def run(self: Any) -> int:")
    run_source = source[run_start:]
    accepted = run_source.index("self.read_prompt")
    dispatch = run_source.index("dispatch_user_request")
    assert accepted < dispatch

    tui_source = Path("src/sophyane/tui_v2.py").read_text(encoding="utf-8")
    cursor_source = Path("src/sophyane/cursor_tab.py").read_text(encoding="utf-8")
    assert "install_cursor_tab_patch" not in run_source or "read_prompt" in cursor_source
    assert "multiline=True" in cursor_source
    assert "_atomic_prompt_submission" in cursor_source


def test_atomic_prompt_preserves_embedded_multiline_submission(monkeypatch):
    import builtins
    from sophyane.tui_v2 import _read_atomic_submission

    objective = "line one\nline two\nline three\nline four"
    monkeypatch.setattr(builtins, "input", lambda _prompt: objective)
    assert _read_atomic_submission("❯ ") == objective


def test_atomic_prompt_single_line_remains_single_submission(monkeypatch):
    import builtins
    from sophyane.tui_v2 import _read_atomic_submission

    monkeypatch.setattr(builtins, "input", lambda _prompt: "one request")
    assert _read_atomic_submission("❯ ") == "one request"


def test_atomic_prompt_buffers_exit_as_separate_control(monkeypatch):
    import builtins
    import sophyane.tui_v2 as tui

    class Buffered:
        def __init__(self):
            self.lines = iter(["line two\n", "line three\n", "exit\n"])
        def readline(self):
            return next(self.lines, "")

    buffered = Buffered()
    monkeypatch.setattr(builtins, "input", lambda _prompt: "line one")
    monkeypatch.setattr(tui.sys, "stdin", buffered)
    monkeypatch.setattr(tui.select, "select", lambda *args: ([buffered], [], []))
    tui._PENDING_TERMINAL_SUBMISSIONS.clear()
    assert tui._read_atomic_submission("❯ ") == "line one\nline two\nline three"
    assert tui._PENDING_TERMINAL_SUBMISSIONS == ["exit"]
    monkeypatch.setattr(tui.select, "select", lambda *args: ([], [], []))
    assert tui._read_atomic_submission("❯ ") == "exit"


def test_cursor_tab_live_prompt_dispatches_buffered_paste_once(monkeypatch):
    import sophyane.cursor_tab as cursor

    class Buffered:
        def __init__(self):
            self.lines = iter([
                "Search local stored memory first.\n",
                "If local memory is sufficient, do not use the internet.\n",
                "Report the exact retrieval route and evidence source.\n",
            ])
        def readline(self):
            return next(self.lines, "")

    buffered = Buffered()
    monkeypatch.setattr(cursor.sys, "stdin", buffered)
    monkeypatch.setattr(cursor.select, "select", lambda *args: ([buffered], [], []))
    cursor._PENDING_SUBMISSIONS.clear()
    objective = "What existing local memory do you have about the Xerus repository?"
    result = cursor._atomic_prompt_submission(lambda _p: objective, "❯ ")
    assert result == objective + "\nSearch local stored memory first.\nIf local memory is sufficient, do not use the internet.\nReport the exact retrieval route and evidence source."
    assert cursor._PENDING_SUBMISSIONS == []


def test_atomic_prompt_captures_late_batch_during_quiescence(monkeypatch):
    import builtins
    import sophyane.tui_v2 as tui

    class Buffered:
        def __init__(self):
            self.lines = iter(["line two\n", "line three\n", "line four\n"])
        def readline(self):
            return next(self.lines, "")

    buffered = Buffered()
    checks = iter([True, True, False, False, True, False])
    monkeypatch.setattr(builtins, "input", lambda _prompt: "line one")
    monkeypatch.setattr(tui.sys, "stdin", buffered)
    monkeypatch.setattr(tui.select, "select", lambda *args: ([buffered], [], []) if next(checks, False) else ([], [], []))
    tui._PENDING_TERMINAL_SUBMISSIONS.clear()
    assert tui._read_atomic_submission("❯ ") == "line one\nline two\nline three\nline four"
