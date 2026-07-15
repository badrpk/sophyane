from __future__ import annotations

from sophyane.daemon_runtime import run_daemon_tick
from sophyane.providers.fallback import (
    FallbackProvider,
    resolve_provider_order,
)
from sophyane.providers.base import Provider, ProviderError, ProviderMetadata
from sophyane.router import route


class _FakeProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="fake",
        display_name="Fake",
        default_model="fake",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(self, name: str, behavior) -> None:
        super().__init__(api_key="", model=name, timeout=5)
        self.name = name
        self.behavior = behavior

    def generate(self, prompt: str, system_prompt: str) -> str:
        return self.behavior(prompt, system_prompt)


def test_fallback_provider_uses_second_backend() -> None:
    def broken(prompt: str, system: str) -> str:
        raise ProviderError("quota")

    def working(prompt: str, system: str) -> str:
        return "ok-from-secondary"

    provider = FallbackProvider(
        [
            ("primary", _FakeProvider("primary", broken)),
            ("secondary", _FakeProvider("secondary", working)),
        ],
        primary="primary",
    )
    assert provider.generate("hi", "sys") == "ok-from-secondary"
    assert provider.last_provider == "secondary"


def test_resolve_provider_order_dedupes_and_includes_ollama() -> None:
    order = resolve_provider_order(
        "openai",
        llm_config={
            "active_provider": "openai",
            "fallback_order": ["gemini", "openai", "xai"],
        },
    )
    assert order[0] == "openai"
    assert order.count("openai") == 1
    assert "gemini" in order
    assert "ollama" in order


def test_router_maps_daemon_tick() -> None:
    assert route("/daemon-tick").kind == "daemon"
    assert route("daemon-tick").kind == "daemon"


def test_daemon_tick_idle_or_ok() -> None:
    report = run_daemon_tick()
    assert report.status in {"idle", "ok", "waiting", "degraded"}
    assert report.version
    text = report.to_text()
    assert "daemon-tick" in text
