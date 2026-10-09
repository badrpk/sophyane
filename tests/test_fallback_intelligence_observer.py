from __future__ import annotations

import pytest

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.fallback import FallbackProvider


class FakeProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="fake",
        display_name="Fake",
        default_model="fake-model",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(self, *, result="ok", error=None, model="fake-model"):
        super().__init__(
            api_key="",
            model=model,
            timeout=30,
        )
        self.result = result
        self.error = error

    def generate(self, prompt, system_prompt):
        if self.error is not None:
            raise self.error
        return self.result


class RecordingObserver:
    def __init__(self):
        self.rows = []

    def record_attempt(self, **row):
        self.rows.append(dict(row))


def test_fallback_records_failure_then_success():
    observer = RecordingObserver()

    provider = FallbackProvider(
        [
            (
                "codex_cli",
                FakeProvider(
                    error=ProviderError("connection failed"),
                    model="codex-default",
                ),
            ),
            (
                "nifdu_browser",
                FakeProvider(
                    result="answered",
                    model="chatgpt-browser",
                ),
            ),
        ],
        primary="codex_cli",
        observer=observer,
    )

    assert provider.generate("SECRET PROMPT", "SECRET SYSTEM") == "answered"

    assert [row["provider"] for row in observer.rows] == [
        "codex_cli",
        "nifdu_browser",
    ]

    assert [row["outcome"] for row in observer.rows] == [
        "failure",
        "success",
    ]

    assert observer.rows[0]["failure_category"]
    assert observer.rows[0]["latency_seconds"] >= 0
    assert observer.rows[1]["latency_seconds"] >= 0

    serialized = repr(observer.rows)

    assert "SECRET PROMPT" not in serialized
    assert "SECRET SYSTEM" not in serialized


def test_observer_failure_never_breaks_successful_generation():
    class BrokenObserver:
        def record_attempt(self, **_row):
            raise RuntimeError("observer unavailable")

    provider = FallbackProvider(
        [
            (
                "nifdu_browser",
                FakeProvider(result="answer"),
            ),
        ],
        primary="nifdu_browser",
        observer=BrokenObserver(),
    )

    assert provider.generate("hello", "system") == "answer"


def test_observer_failure_never_changes_provider_failover():
    class BrokenObserver:
        def record_attempt(self, **_row):
            raise RuntimeError("observer unavailable")

    provider = FallbackProvider(
        [
            (
                "codex_cli",
                FakeProvider(
                    error=ProviderError("connection failed"),
                ),
            ),
            (
                "nifdu_browser",
                FakeProvider(result="fallback-answer"),
            ),
        ],
        primary="codex_cli",
        observer=BrokenObserver(),
    )

    assert provider.generate("hello", "system") == "fallback-answer"
    assert provider.last_provider == "nifdu_browser"


def test_all_provider_failures_are_observed():
    observer = RecordingObserver()

    provider = FallbackProvider(
        [
            (
                "codex_cli",
                FakeProvider(
                    error=ProviderError("connection failed"),
                ),
            ),
            (
                "nifdu_browser",
                FakeProvider(
                    error=RuntimeError("CDP disconnected"),
                ),
            ),
        ],
        primary="codex_cli",
        observer=observer,
    )

    with pytest.raises(ProviderError):
        provider.generate("hello", "system")

    assert [row["provider"] for row in observer.rows] == [
        "codex_cli",
        "nifdu_browser",
    ]

    assert all(
        row["outcome"] == "failure"
        for row in observer.rows
    )

def test_builder_injects_default_intelligence_observer(monkeypatch):
    import sophyane.providers.fallback as module
    import sophyane.intelligence_observer as observer_module
    from sophyane.plugin_loader import PluginLoader

    observer = RecordingObserver()
    monkeypatch.setattr(
        observer_module,
        "default_intelligence_observer",
        lambda: observer,
    )
    monkeypatch.setattr(
        module,
        "resolve_provider_order",
        lambda primary, **_kwargs: ["local_gguf"],
    )
    monkeypatch.setattr(
        module,
        "load_llm_config",
        lambda: {"allow_local_fallbacks": True},
    )
    monkeypatch.setattr(
        PluginLoader,
        "discover",
        lambda self: {"local_gguf": FakeProvider},
    )
    monkeypatch.setattr(
        PluginLoader,
        "create",
        lambda self, provider_id, **kwargs: FakeProvider(
            result="built-answer",
            model=str(kwargs.get("model") or "fake-model"),
        ),
    )

    built = module.build_fallback_provider(
        PluginLoader(),
        {
            "provider": "local_gguf",
            "model": "fake-model",
        },
    )

    assert built.observer is observer
    assert built.generate("SECRET", "SYSTEM") == "built-answer"
    assert observer.rows[-1]["provider"] == "local_gguf"


def test_builder_survives_default_observer_factory_failure(monkeypatch):
    import sophyane.providers.fallback as module
    import sophyane.intelligence_observer as observer_module
    from sophyane.plugin_loader import PluginLoader

    def broken_factory():
        raise OSError("observer storage unavailable")

    monkeypatch.setattr(
        observer_module,
        "default_intelligence_observer",
        broken_factory,
    )
    monkeypatch.setattr(
        module,
        "resolve_provider_order",
        lambda primary, **_kwargs: ["local_gguf"],
    )
    monkeypatch.setattr(
        module,
        "load_llm_config",
        lambda: {"allow_local_fallbacks": True},
    )
    monkeypatch.setattr(
        PluginLoader,
        "discover",
        lambda self: {"local_gguf": FakeProvider},
    )
    monkeypatch.setattr(
        PluginLoader,
        "create",
        lambda self, provider_id, **kwargs: FakeProvider(
            result="still-works",
        ),
    )

    built = module.build_fallback_provider(
        PluginLoader(),
        {"provider": "local_gguf"},
    )

    assert built.generate("hello", "system") == "still-works"
