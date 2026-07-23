from pathlib import Path

from sophyane.browser_partial_recovery import (
    _diagnostic_root,
    _extraction_diagnostic,
    _save_raw,
    _workspace_diagnostic_directory,
)


class AdaptiveStub:
    @staticmethod
    def _extract_html(text: str):
        return (
            text
            if "<html" in text.lower()
            and "</html>" in text.lower()
            else None
        )


def test_save_raw_response_outside_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "user-repository"
    state = tmp_path / "state"
    workspace.mkdir()

    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_DIAGNOSTIC_DIR",
        str(state),
    )

    path = _save_raw(
        workspace,
        2,
        "provider output",
    )

    assert path.name == ".sophyane-provider-response-2.txt"
    assert path.read_text(encoding="utf-8") == "provider output"
    assert path.parent != workspace
    assert state.resolve() in path.resolve().parents
    assert not list(
        workspace.glob(".sophyane-provider-response-*.txt")
    )


def test_current_save_raw_api_is_workspace_isolated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = tmp_path / "state"
    first = tmp_path / "repository-one"
    second = tmp_path / "repository-two"
    first.mkdir()
    second.mkdir()

    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_DIAGNOSTIC_DIR",
        str(state),
    )

    first_path = _save_raw(
        first,
        "run",
        1,
        "first response",
    )
    second_path = _save_raw(
        second,
        "run",
        1,
        "second response",
    )

    assert first_path.parent != second_path.parent
    assert first_path.read_text(encoding="utf-8") == (
        "first response"
    )
    assert second_path.read_text(encoding="utf-8") == (
        "second response"
    )
    assert not list(first.iterdir())
    assert not list(second.iterdir())


def test_diagnostic_root_honours_explicit_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configured = tmp_path / "diagnostics"

    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_DIAGNOSTIC_DIR",
        str(configured),
    )

    assert _diagnostic_root() == configured.resolve()


def test_workspace_diagnostic_directory_is_stable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = tmp_path / "state"
    workspace = tmp_path / "repository"
    workspace.mkdir()

    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_DIAGNOSTIC_DIR",
        str(state),
    )

    first = _workspace_diagnostic_directory(workspace)
    second = _workspace_diagnostic_directory(workspace)

    assert first == second
    assert first.parent == state.resolve()


def test_empty_response_diagnostic() -> None:
    assert _extraction_diagnostic(
        AdaptiveStub,
        "",
    ) == "provider response was empty"


def test_structured_response_without_html_diagnostic() -> None:
    text = '{"action":{"content":"not html"}}'

    assert "structured artifact" in _extraction_diagnostic(
        AdaptiveStub,
        text,
    )


def test_truncated_html_diagnostic() -> None:
    assert "closing </html>" in _extraction_diagnostic(
        AdaptiveStub,
        "<html><body>",
    )


def test_complete_html_diagnostic() -> None:
    text = "prefix <html><body>ok</body></html> suffix"

    assert _extraction_diagnostic(
        AdaptiveStub,
        text,
    ) == "HTML was extracted but failed later validation"
