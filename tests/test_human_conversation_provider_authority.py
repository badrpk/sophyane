"""Mode-6 bounded authority supersedes saved/fixed provider inheritance."""
import pytest


@pytest.mark.parametrize("previous", ["gemini", "nifdu_browser", "codex_cli", "local_gguf", ""])
def test_mode6_authority_ignores_previous_provider(monkeypatch, previous):
    from sophyane.main import create_provider
    from sophyane.intelligence_authority import current_intelligence_authority

    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "human_conversation")
    monkeypatch.setenv("SOPHYANE_SESSION_PROVIDER", previous)
    monkeypatch.setenv("SOPHYANE_SESSION_MODEL", "previous-model")
    provider = create_provider({"provider": "gemini", "model": "saved-model"})
    assert provider.chain == ("codex_cli", "nifdu_browser", "local_gguf")
    authority = current_intelligence_authority()
    assert authority.session_provider == "codex_cli"
    assert authority.session_model == "codex-default"
    assert authority.provider_switching_allowed is False
    assert authority.bounded_provider_failover is True


def test_gemini_conversation_reply_uses_chat_response_mode():
    """conversation_reply must never be constrained by planner JSON schema."""
    from sophyane.providers.gemini import GeminiProvider

    prompt = (
        'SOPHYANE_DISCOVERY_REASONING_REQUEST\\n'
        '{"operation":"conversation_reply",'
        '"discovery_context":{"return_schema":{"reply":"string"}}}'
    )

    assert (
        GeminiProvider._response_mode(
            prompt,
            "Return one valid JSON object only.",
        )
        == "chat"
    )
