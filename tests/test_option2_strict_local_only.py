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

    # Current five-mode startup menu:
    #   2 = SLI Graph
    #   3 = strict Local LLM
    #
    # choose_startup_provider() intentionally writes session policy
    # directly into os.environ. Preserve the caller's environment
    # explicitly so this test cannot leak its selected mode into
    # later tests in the same pytest process.
    env_keys = (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    )

    missing = object()
    original_env = {
        key: startup_policy.os.environ.get(
            key,
            missing,
        )
        for key in env_keys
    }

    try:
        for key in env_keys:
            startup_policy.os.environ.pop(
                key,
                None,
            )

        with patch(
            "builtins.input",
            return_value="3",
        ):
            startup_policy.choose_startup_provider()

        assert (
            startup_policy.os.environ[
                "SOPHYANE_SESSION_MODE"
            ]
            == "local_llm"
        )
        assert (
            startup_policy.os.environ[
                "SOPHYANE_LOCAL_ONLY"
            ]
            == "1"
        )
        assert (
            startup_policy.os.environ[
                "SOPHYANE_DISABLE_CLOUD_FALLBACK"
            ]
            == "1"
        )
    finally:
        for key, value in original_env.items():
            if value is missing:
                startup_policy.os.environ.pop(
                    key,
                    None,
                )
            else:
                startup_policy.os.environ[
                    key
                ] = value

    saved = json.loads(
        llm_file.read_text(encoding="utf-8")
    )

    assert saved["active_provider"] == "local_gguf"
    assert saved["fallback_order"] == ["local_gguf"]
    assert saved["allow_quality_escalation"] is False
    assert saved["quality_rescue_provider"] == ""
    assert saved["allow_cloud_local_rescue"] is False
