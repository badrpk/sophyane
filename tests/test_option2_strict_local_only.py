import io
import json
from unittest.mock import patch

from sophyane import startup_policy


def test_option_two_disables_all_cloud_fallbacks(
    tmp_path,
    monkeypatch,
) -> None:
    llm_file = tmp_path / "llm.json"

    llm_file.write_text(
        json.dumps({
            "active_provider": "gemini",
            "fallback_order": [
                "local_gguf",
                "gemini",
                "openai",
            ],
            "allow_quality_escalation": True,
            "quality_rescue_provider": "gemini",
            "providers": {
                "local_gguf": {
                    "enabled": True,
                    "model": "test.gguf",
                },
                "gemini": {
                    "enabled": True,
                },
            },
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        startup_policy,
        "LLM_FILE",
        llm_file,
    )
    monkeypatch.setattr(
        startup_policy,
        "load_config",
        lambda: {
            "provider": "gemini",
            "model": "gemini-test",
        },
    )
    monkeypatch.setattr(
        startup_policy,
        "_load_llm",
        lambda: json.loads(
            llm_file.read_text(encoding="utf-8")
        ),
    )
    monkeypatch.setattr(
        startup_policy,
        "_local_candidate",
        lambda _config, _llm: (
            "local_gguf",
            "test.gguf",
        ),
    )
    monkeypatch.setattr(
        startup_policy,
        "_configured_clouds",
        lambda: [
            ("gemini", "Google Gemini"),
        ],
    )
    monkeypatch.setattr(
        startup_policy,
        "save_config",
        lambda _config: None,
    )
    monkeypatch.setattr(
        startup_policy.sys.stdin,
        "isatty",
        lambda: True,
    )

    with patch(
        "builtins.input",
        return_value="2",
    ):
        startup_policy.choose_startup_provider()

    saved = json.loads(
        llm_file.read_text(encoding="utf-8")
    )

    assert saved["active_provider"] == "local_gguf"
    assert saved["fallback_order"] == ["local_gguf"]
    assert saved["allow_quality_escalation"] is False
    assert saved["quality_rescue_provider"] == ""
    assert saved["allow_cloud_local_rescue"] is False
