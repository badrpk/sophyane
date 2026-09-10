import pytest


@pytest.mark.parametrize(
    (
        "mode",
        "provider",
        "local_allowed",
        "switching",
        "llm_allowed",
    ),
    (
        (
            "race",
            "",
            True,
            True,
            True,
        ),
        (
            "sli_graph",
            "",
            False,
            False,
            False,
        ),
        (
            "local_llm",
            "local_gguf",
            True,
            False,
            True,
        ),
        (
            "cloud_llm",
            "gemini",
            False,
            False,
            True,
        ),
        (
            "nifdu_llm",
            "nifdu_browser",
            False,
            False,
            True,
        ),
        (
            "codex_cli",
            "codex_cli",
            False,
            False,
            True,
        ),
        (
            "agy",
            "agy",
            False,
            False,
            True,
        ),
        (
            "learning",
            "",
            False,
            False,
            True,
        ),
    ),
)
def test_session_authority_matrix(
    monkeypatch,
    mode,
    provider,
    local_allowed,
    switching,
    llm_allowed,
):
    from sophyane.intelligence_authority import (
        current_intelligence_authority,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        mode,
    )

    if provider:
        monkeypatch.setenv(
            "SOPHYANE_SESSION_PROVIDER",
            provider,
        )
    else:
        monkeypatch.delenv(
            "SOPHYANE_SESSION_PROVIDER",
            raising=False,
        )

    value = (
        current_intelligence_authority()
    )

    assert (
        value.local_reasoning_allowed
        is local_allowed
    )

    assert (
        value.provider_switching_allowed
        is switching
    )

    assert (
        value.llm_allowed
        is llm_allowed
    )


def test_cloud_cannot_use_local_provider(
    monkeypatch,
):
    from sophyane.intelligence_authority import (
        assert_provider_allowed,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "gemini",
    )

    with pytest.raises(
        PermissionError,
        match="AUTHORITY_VIOLATION",
    ):
        assert_provider_allowed(
            "local_gguf"
        )


def test_sli_graph_cannot_use_any_local_llm(
    monkeypatch,
):
    from sophyane.intelligence_authority import (
        assert_provider_allowed,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_graph",
    )

    with pytest.raises(
        PermissionError,
        match="AUTHORITY_VIOLATION",
    ):
        assert_provider_allowed(
            "local_gguf"
        )
