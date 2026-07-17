from __future__ import annotations

import sophyane.providers.gemini as gemini_module
from sophyane.providers.gemini import GeminiProvider


def test_gemini_uses_api_key_header_not_query_string(monkeypatch) -> None:
    captured = {}

    def fake_post_json(url, payload, headers=None, timeout=180):
        captured.update(
            url=url,
            payload=payload,
            headers=headers,
            timeout=timeout,
        )
        return {
            "candidates": [
                {"content": {"parts": [{"text": "GEMINI_OK"}]}}
            ]
        }

    monkeypatch.setattr(gemini_module, "post_json", fake_post_json)
    provider = GeminiProvider(
        api_key="AIza-test-key",
        model="gemini-2.5-flash",
        timeout=25,
    )

    assert provider.generate("hello", "system") == "GEMINI_OK"
    assert captured["url"].endswith(
        "/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert "key=" not in captured["url"]
    assert captured["headers"] == {
        "x-goog-api-key": "AIza-test-key"
    }
    assert captured["timeout"] == 25
