"""Composite provider that tries primary + configured fallbacks."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from sophyane.config import CONFIG_DIR, get_secret
from sophyane.providers.base import Provider, ProviderError, ProviderMetadata
from sophyane.generation_contract import parse_generation_request
from sophyane.runtime_cancel import cancelled


LOGGER = logging.getLogger("sophyane")
LLM_CONFIG_FILE = CONFIG_DIR / "llm.json"
LOCAL_PROVIDER_IDS = {"local_gguf", "ollama"}

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
    """Try providers in order until one succeeds."""

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
            model=str(getattr(first, "model", "") or ""),
            timeout=int(getattr(first, "timeout", 60)),
            temperature=float(getattr(first, "temperature", 0.2)),
            max_tokens=int(getattr(first, "max_tokens", 2048)),
        )
        self._providers = providers
        self.primary = primary or first_name
        self.last_provider = ""
        self.last_errors: list[str] = []

    @property
    def chain(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._providers)

    def get_token_usage(self) -> dict[str, int]:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
        }
        available = False
        for _, provider in self._providers:
            getter = getattr(provider, "get_token_usage", None)
            if not callable(getter):
                continue
            usage = getter()
            if not isinstance(usage, dict):
                continue
            available = True
            for key in totals:
                totals[key] += int(usage.get(key, 0) or 0)
        return {"available": available, **totals}

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        request = parse_generation_request(prompt)

        if request.mode != "raw_artifact":
            result = self._generate_original(prompt, system_prompt)
            self._copy_selected_metadata()
            return result

        errors: list[str] = []
        minimum = max(1, request.minimum_output_tokens)

        for name, provider in self._providers:
            available = int(getattr(provider, "max_tokens", 0) or 0)

            if available < minimum:
                errors.append(
                    f"{name}: skipped; output capacity "
                    f"{available} is below required {minimum}"
                )
                continue

            try:
                result = provider.generate(prompt, system_prompt)
            except Exception as error:
                errors.append(f"{name}: {error}")
                continue

            self.last_provider = name
            self.last_errors = errors
            self._copy_provider_metadata(provider)
            return result

        self.last_errors = errors
        raise ProviderError(
            "No provider can satisfy raw-artifact capacity. "
            + " | ".join(errors)
        )

    def _copy_provider_metadata(self, provider: object) -> None:
        self.last_finish_reason = getattr(
            provider,
            "last_finish_reason",
            "unknown",
        )
        self.last_generation_mode = getattr(
            provider,
            "last_generation_mode",
            "unknown",
        )
        self.last_response_metadata = getattr(
            provider,
            "last_response_metadata",
            {},
        )

        getter = getattr(provider, "get_token_usage", None)
        self.last_token_usage = getter() if callable(getter) else {}

    def _copy_selected_metadata(self) -> None:
        selected = str(getattr(self, "last_provider", "") or "")
        for name, provider in self._providers:
            if name == selected:
                self._copy_provider_metadata(provider)
                return

        self.last_finish_reason = "unknown"
        self.last_generation_mode = "unknown"
        self.last_response_metadata = {}
        self.last_token_usage = {}

    def _generate_original(self, prompt: str, system_prompt: str) -> str:
        errors: list[str] = []

        if cancelled():
            raise ProviderError("provider generation cancelled")

        for name, provider in self._providers:
            if cancelled():
                raise ProviderError("provider generation cancelled")

            started = time.perf_counter()
            try:
                text = provider.generate(prompt, system_prompt)
            except Exception as error:  # noqa: BLE001
                if cancelled():
                    raise ProviderError(
                        "provider generation cancelled"
                    ) from error

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

        # A configured local provider has already attempted the local runtime.
        # Never recurse into Ollama/bootstrap logic after that failure; return
        # control promptly so Termux remains responsive.
        if self.primary in LOCAL_PROVIDER_IDS:
            self.last_errors = errors
            raise ProviderError(
                f"Configured local provider '{self.primary}' failed.\n- "
                + "\n- ".join(errors)
                + "\nStart llama-server on port 8766 or verify the GGUF CLI/runtime path."
            )

        if cancelled():
            raise ProviderError("provider generation cancelled")

        joined = "\n".join(errors)
        try:
            from sophyane.local_runtime import (
                ensure_local_open_model,
                is_credit_or_auth_failure,
            )
            from sophyane.providers.local_gguf import load_gguf_runtime_state

            if is_credit_or_auth_failure(joined):
                LOGGER.warning(
                    "All configured cloud providers failed; bootstrapping local open model"
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
                                    or "http://127.0.0.1:8766"
                                ),
                                "gguf_path": str(state.get("gguf_path") or ""),
                                "cli_path": str(state.get("cli") or ""),
                            }
                        )
                    if cancelled():
                        raise ProviderError(
                            "provider generation cancelled"
                        )

                    local = loader.create(provider_id, **kwargs)

                    if cancelled():
                        raise ProviderError(
                            "provider generation cancelled"
                        )

                    text = local.generate(prompt, system_prompt)
                    self.last_provider = provider_id
                    self.model = result.model
                    self._providers = [(provider_id, local)] + [
                        item for item in self._providers if item[0] != provider_id
                    ]
                    return text
                errors.append(f"local_bootstrap: {result.message}")
        except Exception as bootstrap_error:  # noqa: BLE001
            LOGGER.exception("Local open-model rescue failed")
            errors.append(f"local_bootstrap: {bootstrap_error}")

        self.last_errors = errors
        raise ProviderError(
            "All LLM providers failed. Top up API credits, or run "
            "`sophyane /local` to install a local model.\n- "
            + "\n- ".join(errors)
        )


def load_llm_config() -> dict[str, Any]:
    try:
        from sophyane.config import default_llm_config, ensure_default_llm_files

        ensure_default_llm_files()
    except Exception:  # noqa: BLE001
        default_llm_config = None  # type: ignore[assignment]

    path = LLM_CONFIG_FILE
    if not path.exists():
        return default_llm_config() if callable(default_llm_config) else {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_llm_config() if callable(default_llm_config) else {}
    if not isinstance(data, dict):
        return default_llm_config() if callable(default_llm_config) else {}
    if not data.get("active_provider") and not data.get("fallback_order"):
        base = default_llm_config() if callable(default_llm_config) else {}
        base.update(data)
        return base
    return data


def resolve_provider_order(
    primary: str,
    *,
    llm_config: dict[str, Any] | None = None,
) -> list[str]:
    """Build a de-duplicated provider attempt order.

    Local providers are single-provider by default. Users may opt into an
    explicit fallback chain with ``allow_local_fallbacks: true`` in llm.json.
    """
    cfg = llm_config if llm_config is not None else load_llm_config()
    primary = str(primary or "").strip().lower()

    if primary in LOCAL_PROVIDER_IDS and not bool(cfg.get("allow_local_fallbacks", False)):
        return [primary]

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
    return order


def build_fallback_provider(
    loader: Any,
    config: dict[str, Any],
) -> FallbackProvider:
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
        pcfg = providers_cfg.get(provider_id) or {}
        if isinstance(pcfg, dict) and pcfg.get("enabled") is False:
            continue

        metadata = provider_class.metadata
        api_key = ""
        if metadata.requires_api_key:
            api_key = get_secret(provider_id, metadata.environment_variable)
            if not api_key:
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
                if state.get("model") and not (provider_id == primary and default_model):
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
            "No usable LLM providers are configured. Run `sophyane --setup` or `sophyane /local`."
        )

    return FallbackProvider(chain, primary=primary or chain[0][0])
