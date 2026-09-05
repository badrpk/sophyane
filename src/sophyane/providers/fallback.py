"""Composite provider that tries primary + configured fallbacks."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from sophyane.config import CONFIG_DIR, get_secret
from sophyane.decision_visibility import is_fatal_provider_error
from sophyane.providers.base import Provider, ProviderError, ProviderMetadata
from sophyane.runtime_cancel import cancelled


LOGGER = logging.getLogger("sophyane")
LLM_CONFIG_FILE = CONFIG_DIR / "llm.json"
LOCAL_PROVIDER_IDS = {"local_gguf"}

# Canonical default order when llm.json is missing or incomplete.
DEFAULT_FALLBACK_ORDER = (
    # Mode-4 external intelligence preference: authenticated local Codex
    # first, then browser/CDP harnesses, then API providers.
    "codex_cli",
    "nifdu_browser",
    "agy",
    "gemini",
    "openai",
    "xai",
    "anthropic",
    "groq",
    "openrouter",
    "deepseek",
    "local_gguf",
)


@dataclass
class LocalRescueBudget:
    """Shared wall-clock budget for cloud-to-local rescue generations."""

    remaining_seconds: float
    per_attempt_seconds: float = 60.0

    def available_timeout(
        self,
        configured_timeout: float,
    ) -> int:
        if self.remaining_seconds <= 0:
            return 0

        ceiling = min(
            float(configured_timeout),
            float(self.per_attempt_seconds),
            float(self.remaining_seconds),
        )

        # LocalGgufProvider itself requires a useful positive generation
        # window. A final fractional remainder is therefore unavailable.
        if ceiling < 1.0:
            return 0

        return max(
            1,
            int(ceiling),
        )

    def consume(
        self,
        elapsed_seconds: float,
    ) -> None:
        self.remaining_seconds = max(
            0.0,
            float(self.remaining_seconds)
            - max(0.0, float(elapsed_seconds)),
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

    # SOPHYANE_FALLBACK_GENERATION_BUDGET_V1
    def generate_with_budget(
        self,
        prompt: str,
        system_prompt: str,
        *,
        max_tokens: int,
    ) -> str:
        """Generate with a temporary output-token ceiling.

        The fallback wrapper and its child providers are distinct
        instances. A semantic caller therefore cannot safely constrain
        generation by mutating only ``self.max_tokens``.

        Apply the ceiling transactionally to every provider participating
        in this single fallback attempt, then restore all original values
        even when generation raises.
        """
        budget = max(
            1,
            int(max_tokens),
        )

        wrapper_original = self.max_tokens

        child_originals: list[
            tuple[
                Provider,
                object,
            ]
        ] = []

        try:
            self.max_tokens = min(
                int(
                    self.max_tokens
                    or budget
                ),
                budget,
            )

            for _, provider in self._providers:
                if not hasattr(
                    provider,
                    "max_tokens",
                ):
                    continue

                original = getattr(
                    provider,
                    "max_tokens",
                )

                child_originals.append(
                    (
                        provider,
                        original,
                    )
                )

                try:
                    current = int(
                        original
                        or budget
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    current = budget

                setattr(
                    provider,
                    "max_tokens",
                    min(
                        current,
                        budget,
                    ),
                )

            return self.generate(
                prompt,
                system_prompt,
            )

        finally:
            self.max_tokens = (
                wrapper_original
            )

            for (
                provider,
                original,
            ) in child_originals:
                setattr(
                    provider,
                    "max_tokens",
                    original,
                )

    def generate(
        self,
        prompt: str,
        system_prompt: str,
        *,
        local_rescue_timeout: int | None = None,
        local_rescue_budget: LocalRescueBudget | None = None,
    ) -> str:
        """Generate through the configured provider chain.

        ``local_rescue_timeout`` is an optional per-call ceiling used only
        when a non-local primary has already failed with a permanent
        quota/auth/billing-style error and the next provider is local_gguf.

        Normal local-primary generation keeps its configured timeout.
        Transient cloud failures also keep the normal fallback timeout.

        ``local_rescue_budget`` is shared by all repository-coding backend
        calls in one run. Only real local rescue wall time consumes it.
        Once exhausted, cloud providers remain callable but another local
        rescue is skipped.
        """
        errors: list[str] = []
        hard_cloud_failure_seen = False

        # These fields describe this generate() call, not a previous call.
        self.last_provider = ""
        self.last_errors = []

        if cancelled():
            raise ProviderError("provider generation cancelled")

        for name, provider in self._providers:
            if cancelled():
                raise ProviderError("provider generation cancelled")

            started = time.perf_counter()

            original_timeout = getattr(provider, "timeout", None)

            local_rescue_candidate = (
                name in LOCAL_PROVIDER_IDS
                and self.primary not in LOCAL_PROVIDER_IDS
                and hard_cloud_failure_seen
                and original_timeout is not None
            )

            rescue_timeout = 0

            if local_rescue_candidate:
                if local_rescue_budget is not None:
                    rescue_timeout = (
                        local_rescue_budget.available_timeout(
                            float(original_timeout)
                        )
                    )
                elif local_rescue_timeout is not None:
                    requested = int(local_rescue_timeout)

                    if requested > 0:
                        rescue_timeout = min(
                            int(original_timeout),
                            max(20, requested),
                        )
                else:
                    rescue_timeout = int(original_timeout)

                if rescue_timeout <= 0:
                    errors.append(
                        f"{name}: local rescue skipped: "
                        "shared coding rescue budget exhausted"
                    )
                    continue

            bounded_local_rescue = (
                local_rescue_candidate
                and (
                    local_rescue_budget is not None
                    or local_rescue_timeout is not None
                )
            )

            if bounded_local_rescue:
                provider.timeout = rescue_timeout

            local_started = (
                time.perf_counter()
                if local_rescue_candidate
                else None
            )

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

                if (
                    name not in LOCAL_PROVIDER_IDS
                    and is_fatal_provider_error(error)
                ):
                    hard_cloud_failure_seen = True

                continue

            finally:
                if (
                    local_started is not None
                    and local_rescue_budget is not None
                ):
                    local_rescue_budget.consume(
                        time.perf_counter()
                        - local_started
                    )

                if bounded_local_rescue:
                    provider.timeout = original_timeout

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
        # Never recurse into local-runtime bootstrap logic after that failure; return
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

            cfg = load_llm_config()
            allow_cloud_local_rescue = bool(
                cfg.get("allow_cloud_local_rescue", False)
            )
            # SOPHYANE_STRICT_CLOUD_BOOTSTRAP_BOUNDARY_V2
            # Explicit cloud mode is terminal provider authority. Persisted
            # allow_cloud_local_rescue must not override the selected session.
            import os as _cloud_rescue_policy_os

            session_mode = str(
                _cloud_rescue_policy_os.environ.get(
                    "SOPHYANE_SESSION_MODE"
                )
                or ""
            ).strip().lower()

            disable_local_fallback = (
                str(
                    _cloud_rescue_policy_os.environ.get(
                        "SOPHYANE_DISABLE_LOCAL_FALLBACK"
                    )
                    or ""
                ).strip().lower()
                in {"1", "true", "yes", "on"}
            )

            strict_cloud = (
                session_mode == "cloud_llm"
                or disable_local_fallback
            )


            shared_rescue_available = (
                local_rescue_budget is None
                or local_rescue_budget.remaining_seconds >= 1.0
            )

            if (
                is_credit_or_auth_failure(joined)
                and allow_cloud_local_rescue
                and not strict_cloud
                and shared_rescue_available
            ):
                LOGGER.warning(
                    "Configured cloud providers failed; explicit local rescue "
                    "is enabled, bootstrapping llama.cpp/GGUF"
                )
                result = ensure_local_open_model()
                if result.ok:
                    from sophyane.plugin_loader import PluginLoader

                    loader = PluginLoader()
                    provider_id = result.provider or "local_gguf"
                    bootstrap_timeout = max(
                        self.timeout,
                        300,
                    )

                    if local_rescue_budget is not None:
                        bootstrap_timeout = (
                            local_rescue_budget.available_timeout(
                                float(bootstrap_timeout)
                            )
                        )

                    elif local_rescue_timeout is not None:
                        bootstrap_timeout = min(
                            bootstrap_timeout,
                            max(
                                20,
                                int(local_rescue_timeout),
                            ),
                        )

                    if bootstrap_timeout <= 0:
                        raise ProviderError(
                            "shared coding rescue budget exhausted"
                        )

                    kwargs: dict[str, Any] = {
                        "api_key": "",
                        "model": result.model,
                        "timeout": bootstrap_timeout,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    }
                    if provider_id == "local_gguf":
                        state = load_gguf_runtime_state()
                        kwargs.update(
                            {
                                "endpoint": str(
                                    state.get("endpoint")
                                    or result.runtime_url
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

                    bootstrap_local_started = (
                        time.perf_counter()
                        if provider_id in LOCAL_PROVIDER_IDS
                        else None
                    )

                    try:
                        text = local.generate(
                            prompt,
                            system_prompt,
                        )
                    finally:
                        if (
                            bootstrap_local_started is not None
                            and local_rescue_budget is not None
                        ):
                            local_rescue_budget.consume(
                                time.perf_counter()
                                - bootstrap_local_started
                            )

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
        rate_limited = any(
            marker in joined.casefold()
            for marker in (
                "resource_exhausted",
                "quota exceeded",
                "retrydelay",
                "retry in ",
                "requestsperminute",
                "requests per minute",
            )
        )

        if rate_limited:
            message = (
                "Cloud provider rate limit reached. Retry after the delay "
                "reported by the provider. Automatic local bootstrap is "
                "disabled unless allow_cloud_local_rescue=true.\n- "
            )
        else:
            message = (
                "All configured LLM providers failed. Configure the selected "
                "provider, or explicitly choose local llama.cpp/GGUF mode.\n- "
            )

        raise ProviderError(
            message + "\n- ".join(errors)
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
    order = resolve_provider_order(
        primary,
        llm_config=llm_config,
    )

    # SOPHYANE_STRICT_CLOUD_PROVIDER_CHAIN_V1
    #
    # Session mode is stronger authority than a persisted fallback_order.
    # Explicit cloud_llm means exactly the selected cloud provider: stale
    # llm.json entries must not silently append local_gguf or another backend.
    import os as _provider_policy_os

    session_mode = str(
        _provider_policy_os.environ.get(
            "SOPHYANE_SESSION_MODE"
        )
        or ""
    ).strip().lower()

    disable_local_fallback = (
        str(
            _provider_policy_os.environ.get(
                "SOPHYANE_DISABLE_LOCAL_FALLBACK"
            )
            or ""
        ).strip().lower()
        in {"1", "true", "yes", "on"}
    )

    if session_mode == "cloud_llm":
        # Keep cloud mode free of local rescue, while allowing explicit
        # external harness/browser failover when configured by Mode 4.
        external_failover = str(
            _provider_policy_os.environ.get("SOPHYANE_MODE4_EXTERNAL_FAILOVER") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        if external_failover:
            # Explicit Mode-4 uses one deterministic cross-backend order.
            # Unavailable providers are skipped by the normal discovery/key
            # gates below; no provider is revived by this preference.
            order = list(DEFAULT_FALLBACK_ORDER)
        else:
            order = [primary] if primary else []
    elif disable_local_fallback:
        order = [primary] if primary else []

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
