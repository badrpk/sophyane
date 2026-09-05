from pathlib import Path

SOURCE = Path(
    "src/sophyane/runtime_intent_refinement_patch.py"
)


def test_codex_mode_reaches_native_empty_create():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index(
        "SOPHYANE_NIFDU_DETERMINISTIC_EMPTY_CREATE_V1"
    )
    end = source.index(
        "SOPHYANE_NIFDU_EFFECTIVE_RUN_GUARDED_EXECUTION_V1",
        start,
    )
    section = source[start:end]

    assert "SOPHYANE_NATIVE_EMPTY_CREATE_CROSS_PROVIDER_V1" in section
    assert '"codex_cli"' in section
    assert "deterministic_empty_python_create(" in section
    assert '== "nifdu_llm"' not in section


def test_nontrivial_content_request_is_not_native_empty_create(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        deterministic_empty_python_create,
    )

    result = deterministic_empty_python_create(
        "create game.py containing a snake game",
        workspace=tmp_path,
    )

    assert result is None
    assert not (tmp_path / "game.py").exists()
