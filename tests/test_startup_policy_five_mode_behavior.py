from __future__ import annotations

import builtins
import os

import pytest

import sophyane.startup_policy as startup_policy


STRICT_FLAGS = (
    "SOPHYANE_SLI_ONLY",
    "SOPHYANE_LOCAL_ONLY",
    "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    "SOPHYANE_SLI_CONTINUOUS",
    "SOPHYANE_TOPIC_LEARNING",
)


@pytest.fixture(autouse=True)
def clean_mode_environment(monkeypatch):
    """Isolate startup-policy process environment for every test.

    choose_startup_provider() intentionally writes the selected session
    policy directly through os.environ.  Those writes are application
    behavior, but they must not escape this test into later pytest items.
    """
    keys = (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SLI_GRAPH",
        *STRICT_FLAGS,
    )

    missing = object()

    original = {
        key: os.environ.get(key, missing)
        for key in keys
    }

    for key in keys:
        os.environ.pop(key, None)

    try:
        yield
    finally:
        for key, value in original.items():
            if value is missing:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _invoke(monkeypatch, answer: str):
    config = {
        "provider": "local_gguf",
        "model": "test-local-model",
        "company": "Local",
        "timeout": 60,
    }

    fake_llm = {
        "active_provider": "local_gguf",
        "providers": {
            "local_gguf": {
                "enabled": True,
                "model": "test-local-model",
            },
            "google": {
                "enabled": True,
                "model": "test-cloud-model",
            },
        },
    }

    # pytest stdin is non-interactive by default.
    # Force the production startup policy down the same branch used by
    # a real `sophyane` terminal session.
    monkeypatch.setattr(
        startup_policy.sys.stdin,
        "isatty",
        lambda: True,
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": answer,
    )

    # Load deterministic config/LLM state.
    #
    # choose_startup_provider() owns configuration loading internally,
    # so patch the imported loader seams rather than passing config in.
    for name in (
        "load_config",
        "get_config",
        "_load_config",
    ):
        value = getattr(startup_policy, name, None)
        if callable(value):
            monkeypatch.setattr(
                startup_policy,
                name,
                lambda: dict(config),
            )

    monkeypatch.setattr(
        startup_policy,
        "_load_llm",
        lambda: fake_llm,
    )

    monkeypatch.setattr(
        startup_policy,
        "_local_candidate",
        lambda *_args, **_kwargs: (
            "local_gguf",
            "test-local-model",
        ),
    )

    monkeypatch.setattr(
        startup_policy,
        "_configured_clouds",
        lambda: [
            ("google", "Google Gemini"),
        ],
    )

    monkeypatch.setattr(
        startup_policy,
        "_cloud_model",
        lambda *_args, **_kwargs: "test-cloud-model",
    )

    # No persistent writes.
    if hasattr(startup_policy, "save_config"):
        monkeypatch.setattr(
            startup_policy,
            "save_config",
            lambda *_args, **_kwargs: None,
        )

    if hasattr(startup_policy, "save_json"):
        monkeypatch.setattr(
            startup_policy,
            "save_json",
            lambda *_args, **_kwargs: None,
        )

    # Learning mode must not start real work.
    monkeypatch.setattr(
        startup_policy,
        "_install_topic_learning_mode",
        lambda: None,
    )

    return startup_policy.choose_startup_provider()


@pytest.mark.parametrize("answer", ["", "1"])
def test_default_and_one_select_sophyane_auto(monkeypatch, answer):
    for key in STRICT_FLAGS:
        monkeypatch.setenv(key, "1")

    _invoke(monkeypatch, answer)

    assert os.environ.get("SOPHYANE_SESSION_MODE") == "race"

    for key in STRICT_FLAGS:
        assert key not in os.environ


def test_two_selects_strict_sli(monkeypatch):
    _invoke(monkeypatch, "2")

    assert os.environ.get("SOPHYANE_SESSION_MODE") == "sli_graph"
    assert os.environ.get("SOPHYANE_SLI_GRAPH") == "1"
    assert os.environ.get("SOPHYANE_SLI_ONLY") == "1"


def test_three_selects_strict_local(monkeypatch):
    _invoke(monkeypatch, "3")

    assert os.environ.get("SOPHYANE_SESSION_MODE") == "local_llm"
    assert os.environ.get("SOPHYANE_LOCAL_ONLY") == "1"
    assert (
        os.environ.get("SOPHYANE_DISABLE_CLOUD_FALLBACK")
        == "1"
    )


def test_four_selects_cloud(monkeypatch):
    _invoke(monkeypatch, "4")

    assert os.environ.get("SOPHYANE_SESSION_MODE") == "cloud_llm"


def test_five_selects_learning(monkeypatch):
    _invoke(monkeypatch, "5")

    assert os.environ.get("SOPHYANE_SESSION_MODE") == "learning"
    assert os.environ.get("SOPHYANE_SLI_GRAPH") is None
    assert os.environ.get("SOPHYANE_SLI_ONLY") is None
    assert os.environ.get("SOPHYANE_SLI_CONTINUOUS") == "1"
    assert os.environ.get("SOPHYANE_TOPIC_LEARNING") == "1"


def test_mode2_does_not_persist_transient_sli_config(
    monkeypatch,
):
    writes = []

    monkeypatch.setattr(
        startup_policy,
        "save_config",
        lambda value: writes.append(dict(value)),
    )

    _invoke(
        monkeypatch,
        "2",
    )

    assert writes == []


def test_mode5_does_not_persist_learning_config(
    monkeypatch,
):
    writes = []

    monkeypatch.setattr(
        startup_policy,
        "save_config",
        lambda value: writes.append(dict(value)),
    )

    _invoke(
        monkeypatch,
        "5",
    )

    assert writes == []


@pytest.mark.parametrize(
    "answer,expected_mode",
    [
        ("1", "race"),
        ("3", "local_llm"),
        ("4", "cloud_llm"),
    ],
)
def test_non_sli_modes_clear_stale_sli_and_learning_flags(
    monkeypatch,
    answer,
    expected_mode,
):
    for key in (
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_SLI_CONTINUOUS",
        "SOPHYANE_TOPIC_LEARNING",
    ):
        monkeypatch.setenv(
            key,
            "1",
        )

    _invoke(
        monkeypatch,
        answer,
    )

    assert (
        os.environ.get(
            "SOPHYANE_SESSION_MODE"
        )
        == expected_mode
    )

    for key in (
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_SLI_CONTINUOUS",
        "SOPHYANE_TOPIC_LEARNING",
    ):
        assert (
            os.environ.get(key)
            is None
        )
