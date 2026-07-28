from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sophyane.browser_failure_gate import FAILURE_RESULT, install_browser_failure_gate
from sophyane.providers.gemini import GeminiProvider


def _provider() -> GeminiProvider:
    return GeminiProvider(api_key="test-key", model="gemini-3.6-flash")


def test_response_mode_separates_raw_html_actions_and_plans() -> None:
    provider = _provider()
    assert provider._response_mode(
        "Create one complete self-contained index.html. Output raw HTML only.", ""
    ) == "raw"
    assert provider._response_mode(
        "ADAPTIVE EXECUTION ARTIFACT REQUEST. Return exactly one valid JSON object with write_file.",
        "",
    ) == "action"
    assert provider._response_mode("Plan this coding task", "You are a planner") == "plan"


def test_model_output_limit_is_read_from_gemini(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps({"outputTokenLimit": 131072}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    provider = _provider()
    assert provider._maximum_output_tokens() == 131072
    assert provider._maximum_output_tokens() == 131072


def test_raw_html_uses_full_model_limit_without_json_schema(monkeypatch) -> None:
    provider = _provider()
    monkeypatch.setattr(provider, "_maximum_output_tokens", lambda: 131072)
    captured = []

    def fake_post(_url, payload, timeout):
        captured.append((payload, timeout))
        return {
            "candidates": [{"content": {"parts": [{"text": "<!doctype html><html><body><script>let x=1;</script></body></html>"}]}}],
            "usageMetadata": {},
        }

    monkeypatch.setattr("sophyane.providers.gemini.post_json", fake_post)
    result = provider.generate(
        "Create one complete self-contained index.html and output raw HTML only.", ""
    )
    assert result.startswith("<!doctype html>")
    config = captured[0][0]["generationConfig"]
    assert config["maxOutputTokens"] == 131072
    assert "responseJsonSchema" not in config
    assert "responseMimeType" not in config


def test_malformed_plan_retries_same_gemini_with_action_schema(monkeypatch) -> None:
    provider = _provider()
    monkeypatch.setattr(provider, "_maximum_output_tokens", lambda: 65536)
    calls = []

    def fake_post(_url, payload, timeout):
        calls.append(json.loads(json.dumps(payload)))
        if len(calls) == 1:
            return {
                "candidates": [{"content": {}, "finishReason": "MALFORMED_RESPONSE"}],
                "usageMetadata": {},
            }
        return {
            "candidates": [{"content": {"parts": [{"text": '{"action":{"type":"respond","message":"ok"}}'}]}}],
            "usageMetadata": {},
        }

    monkeypatch.setattr("sophyane.providers.gemini.post_json", fake_post)
    result = provider.generate("Plan and execute this task", "You are a planner")
    assert json.loads(result)["action"]["type"] == "respond"
    assert len(calls) == 2
    assert calls[0]["generationConfig"]["maxOutputTokens"] == 65536
    assert calls[1]["generationConfig"]["maxOutputTokens"] == 65536
    assert "files" in calls[1]["generationConfig"]["responseJsonSchema"]["properties"]


def test_browser_failure_gate_blocks_generic_fallback_on_provider_exception(
    tmp_path: Path, monkeypatch
) -> None:
    from sophyane import adaptive_execution as adaptive

    original = adaptive._one_shot_browser_artifact

    def exploding(**_kwargs):
        raise RuntimeError("provider malformed response")

    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", exploding)
    install_browser_failure_gate()
    result = adaptive._one_shot_browser_artifact(
        ask=lambda _prompt: SimpleNamespace(text=""),
        original_request="make snake game",
        workspace=tmp_path,
        progress=lambda _message: None,
    )
    assert result.startswith(FAILURE_RESULT)
    assert "RuntimeError" in result
    monkeypatch.setattr(adaptive, "_one_shot_browser_artifact", original)
