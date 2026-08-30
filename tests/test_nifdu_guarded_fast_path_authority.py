from pathlib import Path


SOURCE = Path(
    "src/sophyane/runtime_intent_refinement_patch.py"
)


def _section() -> str:
    text = SOURCE.read_text(
        encoding="utf-8",
    )

    start = text.index(
        "SOPHYANE_NIFDU_GUARDED_FAST_PATH_V2"
    )

    end = text.index(
        "Planning with NIFDU; native Sophyane runtime",
        start,
    )

    return text[start:end]


def test_guarded_file_executor_precedes_generic_nifdu():
    text = SOURCE.read_text(
        encoding="utf-8",
    )

    marker = text.index(
        "SOPHYANE_NIFDU_GUARDED_FAST_PATH_V2"
    )

    guarded = text.index(
        "execute_nifdu_file_request(",
        marker,
    )

    generic = text.index(
        "_nifdu_initial = self.call_provider(",
        marker,
    )

    assert guarded < generic


def test_guarded_executor_uses_real_signature():
    section = _section()

    assert (
        "workspace=_nifdu_workspace"
        in section
    )

    assert "ask=lambda" not in section


def test_guarded_result_is_path_not_handled_dict():
    section = _section()

    assert (
        "_nifdu_guarded_path"
        in section
    )

    assert (
        "_nifdu_guarded_path is not None"
        in section
    )

    assert (
        ".is_file()"
        in section
    )


def test_guarded_path_is_workspace_bounded():
    section = _section()

    assert (
        ".relative_to("
        in section
    )

    assert (
        "outside the active workspace"
        in section
    )


def test_verified_path_terminalizes_before_adaptive_loop():
    section = _section()

    assert '"handled": True' in section
    assert '"ok": True' in section
    assert "self.emit(" in section
    assert "continue" in section


def test_generic_nifdu_fallback_remains():
    text = SOURCE.read_text(
        encoding="utf-8",
    )

    marker = text.index(
        "SOPHYANE_NIFDU_GUARDED_FAST_PATH_V2"
    )

    tail = text[marker:]

    assert (
        "_nifdu_initial = self.call_provider("
        in tail
    )

    assert (
        "tui_v2.run_structured_loop("
        in tail
    )
