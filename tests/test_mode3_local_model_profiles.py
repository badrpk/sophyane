from __future__ import annotations

import builtins
import os

import pytest


_TRANSIENT_LOCAL_KEYS = (
    "SOPHYANE_SESSION_MODE",
    "SOPHYANE_SESSION_PROVIDER",
    "SOPHYANE_SESSION_MODEL",
    "SOPHYANE_SESSION_TIMEOUT",
    "SOPHYANE_LOCAL_PROFILE",
    "SOPHYANE_LLAMA_SERVER",
    "SOPHYANE_LLAMA_CONTEXT",
    "SOPHYANE_LOCAL_ONLY",
    "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    "SOPHYANE_DISABLE_LOCAL_FALLBACK",
    "SOPHYANE_ALLOW_CLOUD_LOCAL_RESCUE",
)


@pytest.fixture(autouse=True)
def isolate_local_profile_environment():
    missing = object()

    original = {
        key: os.environ.get(key, missing)
        for key in _TRANSIENT_LOCAL_KEYS
    }

    for key in _TRANSIENT_LOCAL_KEYS:
        os.environ.pop(key, None)

    try:
        yield
    finally:
        for key, value in original.items():
            if value is missing:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_profile_configuration_selects_spark(
    monkeypatch,
):
    import sophyane.local_model_profiles as profiles

    monkeypatch.setattr(
        profiles,
        "spark_profile_available",
        lambda: True,
    )

    monkeypatch.setattr(
        profiles,
        "SPARK_MODEL",
        profiles.Path(
            "/tmp/spark.gguf"
        ),
    )

    monkeypatch.setattr(
        profiles,
        "SPARK_SERVER",
        profiles.Path(
            "/tmp/llama-server"
        ),
    )

    selected = (
        profiles.configure_session_profile(
            "spark",
            qwen_model="qwen-test",
        )
    )

    assert selected["profile"] == "spark"
    assert (
        os.environ[
            "SOPHYANE_LOCAL_PROFILE"
        ]
        == "spark"
    )
    assert (
        os.environ[
            "SOPHYANE_LLAMA_SERVER"
        ]
        == "http://127.0.0.1:8767"
    )


def test_mode3_menu_can_select_compare(
    monkeypatch,
):
    import sophyane.startup_policy as policy
    import sophyane.local_model_profiles as profiles

    monkeypatch.setattr(
        policy.sys.stdin,
        "isatty",
        lambda: True,
    )

    monkeypatch.setattr(
        policy,
        "load_config",
        lambda: {
            "provider": "local_gguf",
            "model": "qwen-test",
            "timeout": 300,
        },
    )

    monkeypatch.setattr(
        policy,
        "_load_llm",
        lambda: {
            "active_provider": "local_gguf",
            "providers": {
                "local_gguf": {
                    "enabled": True,
                    "model": "qwen-test",
                },
            },
        },
    )

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda *_args, **_kwargs: (
            "local_gguf",
            "qwen-test",
        ),
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    monkeypatch.setattr(
        profiles,
        "spark_profile_available",
        lambda: True,
    )

    monkeypatch.setattr(
        policy,
        "save_json",
        lambda *_args, **_kwargs: None,
    )

    answers = iter(
        (
            "3",
            "3",
        )
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(
            answers
        ),
    )

    result = (
        policy.choose_startup_provider()
    )

    assert (
        os.environ[
            "SOPHYANE_SESSION_MODE"
        ]
        == "local_llm"
    )
    assert (
        os.environ[
            "SOPHYANE_LOCAL_PROFILE"
        ]
        == "compare"
    )
    assert (
        result["model"]
        == "qwen2.5-1.5b-vs-spark-x2.5-4b"
    )


def test_local_provider_resolves_endpoint_at_instance_time(
    monkeypatch,
):
    from sophyane.providers.local_gguf import (
        LocalGgufProvider,
    )

    monkeypatch.setenv(
        "SOPHYANE_LLAMA_SERVER",
        "http://127.0.0.1:9876",
    )

    provider = LocalGgufProvider()

    assert (
        provider.endpoint
        == "http://127.0.0.1:9876"
    )


def test_compare_bounds_output_and_spark_reasoning_only():
    from pathlib import Path

    text = Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text()

    assert "completion_budget = min(" in text
    assert "completion_budget," in text
    assert "512," in text

    assert 'if "spark" in model.lower():' in text
    assert '"reasoning_budget_tokens"' in text
    assert "] = 128" in text


def test_compare_receives_shared_local_prompt_bounds_before_branch():
    from pathlib import Path

    text = Path("src/sophyane/providers/local_gguf.py").read_text()

    generate_start = text.index(
        "    def generate(self, prompt: str, system_prompt: str) -> str:"
    )
    compare_branch = text.index(
        '        if local_profile == "compare":',
        generate_start,
    )
    system_bound = text.index(
        '        system_prompt = (system_prompt or "")[:800]',
        generate_start,
    )
    prompt_bound = text.index(
        '        prompt = (prompt or "")[:4000]',
        generate_start,
    )

    assert system_bound < compare_branch
    assert prompt_bound < compare_branch
    assert text.count(
        'system_prompt = (system_prompt or "")[:800]'
    ) == 1
    assert text.count(
        'prompt = (prompt or "")[:4000]'
    ) == 1


def test_compare_profile_bypasses_repository_coding_runtime():
    from pathlib import Path

    text = Path("src/sophyane/v13_cli.py").read_text()

    marker = "# SOPHYANE_MODE3_COMPARE_DIRECT_BENCHMARK_V1"
    assert marker in text

    start = text.index(marker)
    section = text[start:start + 1800]

    assert 'os.environ.get("SOPHYANE_LOCAL_PROFILE")' in section
    assert 'local_profile == "compare"' in section
    assert "compare_benchmark" in section
    assert "force_chat = (" in section

    force_chat_branch = text.index(
        "    if force_chat and not args.single_agent and not args.multi_agent:",
        start,
    )
    strict_runtime = text.index(
        "    runtime = StrictInteractiveCodingDoerRuntime(",
        start,
    )

    assert force_chat_branch < strict_runtime


def test_mode3_compare_has_authoritative_tui_leaf():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_provider_context_patch.py"
    ).read_text()

    marker = "# SOPHYANE_MODE3_COMPARE_LEAF_AUTHORITY_V1"
    assert marker in text

    section = text[
        text.index("_local_compare_authoritative")
        :text.index(marker) + 1400
    ]

    assert '"SOPHYANE_LOCAL_PROFILE"' in section
    assert '== "compare"' in section
    assert 'primary == "local_gguf"' in section
    assert "LOCAL_CHAT_SYSTEM_PROMPT" in section
    assert "provider.generate(" in section


def test_mode3_compare_short_circuits_effective_tui_turn():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text()

    preflight = text.index(
        "# SOPHYANE_AUTHORITATIVE_OBJECTIVE_PREFLIGHT"
    )

    marker = "# SOPHYANE_MODE3_COMPARE_SINGLE_TURN_V1"
    start = text.index(marker)

    handoff = text.index(
        "# SOPHYANE_NIFDU_NATIVE_EXECUTION_HANDOFF_V1",
        start,
    )

    assert preflight < start < handoff

    section = text[start:handoff]

    assert '"SOPHYANE_SESSION_MODE"' in section
    assert '"SOPHYANE_LOCAL_PROFILE"' in section
    assert '_compare_local_profile == "compare"' in section
    assert "Running direct local model comparison" in section
    assert "self.call_provider(" in section
    assert "continue" in section
