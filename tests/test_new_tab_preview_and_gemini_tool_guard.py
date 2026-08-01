from pathlib import Path

from sophyane import browser_runtime_v2
from sophyane.providers import gemini as gemini_module
from sophyane.providers.gemini import GeminiProvider


def test_desktop_preview_uses_new_tab_api(monkeypatch):
    monkeypatch.setattr(browser_runtime_v2.shutil, "which", lambda _name: None)
    opened = []
    monkeypatch.setattr(
        browser_runtime_v2.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or True,
    )

    ok, detail = browser_runtime_v2._desktop_new_tab("http://127.0.0.1:8123/index.html")

    assert ok is True
    assert opened == ["http://127.0.0.1:8123/index.html"]
    assert "new-tab" in detail


def test_verified_preview_opens_after_http_hash_check(tmp_path: Path, monkeypatch):
    html = (
        "<!doctype html><html><body><main><h1>Verified product preview</h1>"
        "<p>This fixture intentionally exceeds the minimum browser-artifact safety size.</p>"
        "</main><script>let x=1;document.body.dataset.ready=String(x);</script>"
        "</body></html>"
    )
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(browser_runtime_v2.shutil, "which", lambda _name: None)
    opened = []
    monkeypatch.setattr(
        browser_runtime_v2.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or True,
    )

    ok, detail = browser_runtime_v2.open_verified_browser(tmp_path, lambda _message: None)

    assert ok is True
    assert len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:")
    assert "/index.html?v=" in opened[0]
    assert "SHA-256 matched" in detail


def test_gemini_disables_native_function_calling(monkeypatch):
    provider = GeminiProvider("key", "gemini-3.6-flash")
    provider._model_output_limit = 65536
    payloads = []

    def fake_post_json(_url, payload, timeout):
        payloads.append(payload)
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "<!doctype html><html><body>ok</body></html>"}
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(gemini_module, "post_json", fake_post_json)
    result = provider.generate(
        "Output raw HTML only, beginning <!doctype html> and ending </html>.",
        "Return the final artifact directly.",
    )

    assert result.startswith("<!doctype html>")
    assert payloads[0]["toolConfig"]["functionCallingConfig"]["mode"] == "NONE"


def test_gemini_retries_unexpected_function_call(monkeypatch):
    provider = GeminiProvider("key", "gemini-3.6-flash")
    provider._model_output_limit = 65536
    prompts = []
    responses = iter(
        [
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"functionCall": {"name": "default:list_dir", "args": {}}}
                            ]
                        }
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "<!doctype html><html><body>retry ok</body></html>"}
                            ]
                        }
                    }
                ]
            },
        ]
    )

    def fake_post_json(_url, payload, timeout):
        prompts.append(payload["contents"][0]["parts"][0]["text"])
        return next(responses)

    monkeypatch.setattr(gemini_module, "post_json", fake_post_json)
    result = provider.generate(
        "Output raw HTML only, beginning <!doctype html> and ending </html>.",
        "Return the artifact.",
    )

    assert "retry ok" in result
    assert len(prompts) == 2
    assert prompts[1].startswith("Do not call tools or functions.")
