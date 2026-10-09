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

# SOPHYANE_MODE6_LLM_ONLY_AUTHORITY_V1
def test_mode6_disallows_independent_local_reasoning_but_keeps_bounded_llm_cascade(
    monkeypatch,
):
    from sophyane.intelligence_authority import (
        assert_provider_allowed,
        current_intelligence_authority,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "codex_cli",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "codex-default",
    )

    authority = current_intelligence_authority()

    assert authority.local_reasoning_allowed is False
    assert authority.llm_allowed is True
    assert authority.provider_switching_allowed is False
    assert authority.bounded_provider_failover is True
    assert tuple(authority.provider_failover_order) == (
        "codex_cli",
        "nifdu_browser",
    )

    # Only the two cloud transports are authorized in the bounded Mode-6
    # cascade.
    for provider in authority.provider_failover_order:
        assert_provider_allowed(provider)

    import pytest

    # Local GGUF and arbitrary provider switching are both forbidden.
    with pytest.raises(PermissionError):
        assert_provider_allowed("local_gguf")

    with pytest.raises(PermissionError):
        assert_provider_allowed("gemini")
