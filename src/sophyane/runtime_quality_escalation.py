"""Validator-triggered one-shot cloud rescue for weak local-model repairs.

The normal provider fallback handles transport/API failures. This patch handles a
second failure mode: a responsive local model that repeatedly returns output
which deterministic validators reject. After a bounded number of repair
prompts, Sophyane asks one configured cloud provider for a single expert repair,
then automatically returns to the local provider for subsequent work.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

LOGGER = logging.getLogger("sophyane")
LOCAL_PROVIDER_IDS = {"local_gguf", "ollama"}


def _provider_id(provider: Any) -> str:
    metadata = getattr(provider, "metadata", None)
    return str(
        getattr(metadata, "provider_id", "")
        or getattr(provider, "provider_id", "")
        or ""
    ).strip().lower()


def _is_repair_prompt(prompt: str) -> bool:
    text = " ".join(str(prompt or "").lower().split())
    strong_markers = (
        "repairing incomplete",
        "previous response",
        "previous html",
        "validation failed",
        "validator",
        "failed verification",
        "missing required",
        "still missing",
        "no keyboard or touch controls",
        "return a corrected",
        "continue the same task",
    )
    if any(marker in text for marker in strong_markers):
        return True
    return bool(
        re.search(r"\b(repair|fix|correct)\b", text)
        and re.search(r"\b(previous|failed|missing|invalid|incomplete|validator)\b", text)
    )


def install_quality_escalation() -> None:
    """Install once before providers are constructed."""
    from sophyane.providers import fallback

    if getattr(fallback, "_quality_escalation_installed", False):
        return

    original_resolve = fallback.resolve_provider_order
    original_generate = fallback.FallbackProvider.generate

    def resolve_provider_order(
        primary: str,
        *,
        llm_config: dict[str, Any] | None = None,
    ) -> list[str]:
        cfg = llm_config if llm_config is not None else fallback.load_llm_config()
        primary_id = str(primary or "").strip().lower()
        order = original_resolve(primary_id, llm_config=cfg)

        # Local-first installations gain a bounded rescue chain automatically.
        # Missing credentials are skipped later by build_fallback_provider, so
        # this never invents access or sends requests to unconfigured services.
        enabled = bool(cfg.get("allow_quality_escalation", True))
        if primary_id not in LOCAL_PROVIDER_IDS or not enabled:
            return order

        def add(name: object) -> None:
            value = str(name or "").strip().lower()
            if value and value not in order and value not in {"fallback", *LOCAL_PROVIDER_IDS}:
                order.append(value)

        add(cfg.get("quality_rescue_provider"))
        for name in cfg.get("fallback_order", []) or []:
            add(name)
        for name in fallback.DEFAULT_FALLBACK_ORDER:
            add(name)
        return order

    def generate(self: Any, prompt: str, system_prompt: str) -> str:
        primary = str(getattr(self, "primary", "") or "").strip().lower()
        if primary not in LOCAL_PROVIDER_IDS:
            return original_generate(self, prompt, system_prompt)

        repair = _is_repair_prompt(prompt)
        streak = int(getattr(self, "_quality_repair_streak", 0) or 0)
        streak = streak + 1 if repair else 0
        self._quality_repair_streak = streak

        threshold = 2
        try:
            from sophyane.providers.fallback import load_llm_config

            cfg = load_llm_config()
            threshold = max(1, int(cfg.get("quality_escalation_after", 2) or 2))
            enabled = bool(cfg.get("allow_quality_escalation", True))
        except Exception:  # noqa: BLE001
            enabled = True

        cloud = [
            (name, provider)
            for name, provider in getattr(self, "_providers", [])
            if name not in LOCAL_PROVIDER_IDS
        ]

        if enabled and repair and streak >= threshold and cloud:
            errors: list[str] = []
            for name, provider in cloud:
                started = time.perf_counter()
                try:
                    text = provider.generate(prompt, system_prompt)
                except Exception as error:  # noqa: BLE001
                    errors.append(f"{name}: {type(error).__name__}: {error}")
                    LOGGER.warning("Quality rescue provider %s failed: %s", name, error)
                    continue

                elapsed_ms = (time.perf_counter() - started) * 1000
                self.last_provider = name
                self.last_errors = errors
                self.model = provider.model
                self._quality_repair_streak = 0
                LOGGER.warning(
                    "Validator-triggered quality rescue succeeded via %s in %.0fms; returning to %s next call",
                    name,
                    elapsed_ms,
                    primary,
                )
                return text

            LOGGER.warning(
                "Configured quality rescue providers failed; continuing bounded local recovery: %s",
                "; ".join(errors),
            )

        # Normal call remains local-first. Transport failures can still use the
        # ordinary fallback chain. A successful cloud rescue above is one-shot;
        # this path resumes the configured local provider on the next call.
        return original_generate(self, prompt, system_prompt)

    fallback.resolve_provider_order = resolve_provider_order
    fallback.FallbackProvider.generate = generate
    fallback._quality_escalation_installed = True
