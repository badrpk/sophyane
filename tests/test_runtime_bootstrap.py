from __future__ import annotations

import sophyane.runtime_bootstrap as runtime


def test_stale_gemini_model_is_normalized(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        runtime,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-3.5-flash",
            "timeout": 60,
            "max_tokens": 4096,
        },
    )
    monkeypatch.setattr(runtime, "detect_device", lambda: {
        "termux": False,
        "memory_mb": 8192,
    })
    monkeypatch.setattr(runtime, "load_secrets", lambda: {})
    monkeypatch.setattr(runtime, "save_config", lambda value: saved.update(value))
    monkeypatch.setattr(runtime, "save_secret", lambda *_: None)

    result = runtime.bootstrap_runtime()

    assert result["config"]["model"] == "gemini-2.5-flash"
    assert result["config"]["runtime_profile"] == "desktop"
    assert saved["model"] == "gemini-2.5-flash"


def test_termux_low_memory_profile(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "timeout": 180,
            "max_tokens": 8192,
        },
    )
    monkeypatch.setattr(runtime, "detect_device", lambda: {
        "termux": True,
        "memory_mb": 4096,
    })
    monkeypatch.setattr(runtime, "load_secrets", lambda: {})
    monkeypatch.setattr(runtime, "save_config", lambda *_: None)
    monkeypatch.setattr(runtime, "save_secret", lambda *_: None)

    config = runtime.bootstrap_runtime()["config"]

    assert config["runtime_profile"] == "termux"
    assert config["timeout"] == 120
    assert config["max_tokens"] == 2048
