from pathlib import Path


SOURCE = Path(
    "src/sophyane/runtime_provider_context_patch.py"
)


def test_codex_session_has_direct_leaf_provider_authority():
    source = SOURCE.read_text(encoding="utf-8")

    assert (
        "SOPHYANE_CODEX_LEAF_PROVIDER_CALL_AUTHORITY_V1"
        in source
    )
    assert '_session_mode == "codex_cli"' in source
    assert '_resolved_provider_id\n                            == "codex_cli"' in source
    assert "_codex_leaf_authoritative" in source
    assert "_direct_leaf_authoritative" in source


def test_direct_leaf_path_calls_provider_generate():
    source = SOURCE.read_text(encoding="utf-8")

    start = source.index(
        "SOPHYANE_CODEX_LEAF_PROVIDER_CALL_AUTHORITY_V1"
    )
    section = source[start : start + 2200]

    assert "if _direct_leaf_authoritative:" in section
    assert "value = provider.generate(" in section


def test_non_leaf_sessions_preserve_self_ask_fallback():
    source = SOURCE.read_text(encoding="utf-8")

    start = source.index(
        "SOPHYANE_CODEX_LEAF_PROVIDER_CALL_AUTHORITY_V1"
    )
    section = source[start : start + 2200]

    assert "else:" in section
    assert "value = self.ask(" in section
