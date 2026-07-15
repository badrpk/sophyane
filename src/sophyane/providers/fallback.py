"""Composite provider that tries primary + configured fallbacks."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from sophyane.config import CONFIG_DIR, get_secret
from sophyane.providers.base import Provider, ProviderError, ProviderMetadata


LOGGER = logging.getLogger("sophyane")
LLM_CONFIG_FILE = CONFIG_DIR / "llm.json"

# Canonical default order when llm.json is missing or incomplete.
DEFAULT_FALLBACK_ORDER = (
    "gemini",
    "xai",
    "openai",
    "anthropic",
    "groq",
    "openrouter",
    "deepseek",
    "ollama",
    "local_gguf",
)


class FallbackProvider(Provider):
    """Try providers in order until one succeeds.

    Quota, auth, and network failures fall through to the next provider.
    """

    metadata = ProviderMetadata(
        provider_id="fallback",
        display_name="Multi-provider fallback",
        default_model="auto",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        providers: list[tuple[str, Provider]],
        *,
        primary: str = "",
    ) -> None:
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider")
        first_name, first = providers[0]
        super().__init__(
            api_key="",
            model=first.model,
            timeout=first.timeout,
            temperature=first.temperature,
            max_tokens=first.max_tokens,
        )
        self._providers = providers
        self.primary = primary or first_name
        self.last_provider = ""
        self.last_errors: list[str] = []

    @property
    def chain(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._providers)

    def generate(self, prompt: str, system_prompt: str) -> str:
        errors: list[str] = []
        for name, provider in self._providers:
            started = time.perf_counter()
            try:
                text = provider.generate(prompt, system_prompt)
            except Exception as error:  # noqa: BLE001 — fall through intentionally
                latency_ms = (time.perf_counter() - started) * 1000
                message = f"{name}: {type(error).__name__}: {error}"
                errors.append(message)
                LOGGER.warning(
                    "Provider %s failed in %.0fms: %s",
                    name,
                    latency_ms,
                    error,
                )
                continue

            self.last_provider = name
            self.last_errors = errors
            self.model = provider.model
            if errors:
                LOGGER.info(
                    "Provider fallback succeeded via %s after: %s",
                    name,
                    "; ".join(errors),
                )
            return text

        # Automatic open-model rescue: Ollama first, then Hugging Face GGUF
        # + GitHub llama.cpp when frontier APIs have no credits.
        joined = "\n".join(errors)
        try:
            from sophyane.local_runtime import (
                ensure_local_open_model,
                is_credit_or_auth_failure,
            )
            from sophyane.providers.local_gguf import load_gguf_runtime_state

            if is_credit_or_auth_failure(joined):
                LOGGER.warning(
                    "All configured providers failed; bootstrapping local open model"
                )
                result = ensure_local_open_model()
                if result.ok:
                    from sophyane.plugin_loader import PluginLoader

                    loader = PluginLoader()
                    provider_id = result.provider or "local_gguf"
                    kwargs: dict[str, Any] = {
                        "api_key": "",
                        "model": result.model,
                        "timeout": max(self.timeout, 300),
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    }
                    if provider_id == "local_gguf":
                        state = load_gguf_runtime_state()
                        kwargs.update(
                            {
                                "endpoint": str(
                                    state.get("endpoint")
                                    or result.ollama_url
                                    or "http://127.0.0.1:8765"
                                ),
                                "gguf_path": str(state.get("gguf_path") or ""),
                                "cli_path": str(state.get("cli") or ""),
                            }
                        )
                    local = loader.create(provider_id, **kwargs)
                    text = local.generate(prompt, system_prompt)
                    self.last_provider = provider_id
                    self.model = result.model
                    self._providers = [(provider_id, local)] + [
                        item for item in self._providers if item[0] != provider_id
                    ]
                    LOGGER.info(
                        "Serving via auto-installed local model %s/%s",
                        provider_id,
                        result.model,
                    )
                    return text
                errors.append(f"local_bootstrap: {result.message}")
        except Exception as bootstrap_error:  # noqa: BLE001
            LOGGER.exception("Local open-model rescue failed")
            errors.append(f"local_bootstrap: {bootstrap_error}")

        self.last_errors = errors
        raise ProviderError(
            "All LLM providers failed. "
            "Top up API credits, or run `sophyane /local` to install "
            "Ollama or a Hugging Face GGUF open model.\n- "
            + "\n- ".join(errors)
        )


def load_llm_config() -> dict[str, Any]:
    path = LLM_CONFIG_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_provider_order(
    primary: str,
    *,
    llm_config: dict[str, Any] | None = None,
) -> list[str]:
    """Build a de-duplicated provider attempt order."""
    cfg = llm_config if llm_config is not None else load_llm_config()
    order: list[str] = []

    def add(name: str) -> None:
        name = str(name or "").strip().lower()
        if name and name not in order and name != "fallback":
            order.append(name)

    add(primary)
    add(str(cfg.get("active_provider", "")))

    for name in cfg.get("fallback_order", []) or []:
        add(str(name))

    for name in DEFAULT_FALLBACK_ORDER:
        add(name)

    # Prefer local last when cloud is preferred, but always include locals.
    if "ollama" not in order:
        order.append("ollama")
    if "local_gguf" not in order:
        order.append("local_gguf")
    return order


def build_fallback_provider(
    loader: Any,
    config: dict[str, Any],
) -> FallbackProvider:
    """Instantiate every available provider and wrap them in FallbackProvider."""
    from sophyane.plugin_loader import PluginLoader

    if not isinstance(loader, PluginLoader):
        loader = PluginLoader()

    discovered = loader.discover()
    llm_config = load_llm_config()
    primary = str(config.get("provider", "")).strip().lower()
    order = resolve_provider_order(primary, llm_config=llm_config)

    providers_cfg = llm_config.get("providers") or {}
    timeout = int(config.get("timeout", 180))
    temperature = float(config.get("temperature", 0.3))
    max_tokens = int(config.get("max_tokens", 4096))
    default_model = str(config.get("model", "")).strip()

    chain: list[tuple[str, Provider]] = []
    for provider_id in order:
        provider_class = discovered.get(provider_id)
        if provider_class is None:
            continue

        # Skip explicitly disabled providers from llm.json.
        pcfg = providers_cfg.get(provider_id) or {}
        if isinstance(pcfg, dict) and pcfg.get("enabled") is False:
            continue

        metadata = provider_class.metadata
        api_key = ""
        if metadata.requires_api_key:
            api_key = get_secret(provider_id, metadata.environment_variable)
            if not api_key:
                # Secondary env aliases commonly used for Gemini.
                if provider_id == "gemini":
                    api_key = get_secret("gemini", "GOOGLE_API_KEY")
                if not api_key:
                    continue

        model = default_model if provider_id == primary and default_model else ""
        if not model and isinstance(pcfg, dict):
            model = str(pcfg.get("model") or "").strip()
        if not model:
            model = metadata.default_model

        create_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "model": model,
            "timeout": timeout,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if provider_id == "local_gguf":
            try:
                from sophyane.providers.local_gguf import load_gguf_runtime_state

                state = load_gguf_runtime_state()
                if state.get("gguf_path"):
                    create_kwargs["gguf_path"] = str(state["gguf_path"])
                if state.get("cli"):
                    create_kwargs["cli_path"] = str(state["cli"])
                if state.get("endpoint"):
                    create_kwargs["endpoint"] = str(state["endpoint"])
                if state.get("model") and not (
                    provider_id == primary and default_model
                ):
                    create_kwargs["model"] = str(state["model"])
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("local_gguf state load failed: %s", error)

        try:
            instance = loader.create(provider_id, **create_kwargs)
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("Skipping provider %s: %s", provider_id, error)
            continue
        chain.append((provider_id, instance))

    if not chain:
        raise ProviderError(
            "No usable LLM providers are configured. "
            "Run `sophyane --setup`, `sophyane /local`, or start Ollama."
        )

    return FallbackProvider(chain, primary=primary or chain[0][0])
