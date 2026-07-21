"""Validator-triggered cloud rescue for weak local-model repairs.

The normal provider fallback handles transport/API failures. This patch handles a
second failure mode: a responsive local model that repeatedly returns output
which deterministic validators reject. After a bounded number of local repair
prompts, Sophyane transfers ownership of the current repair sequence to one
configured cloud provider. The cloud provider remains responsible while the
runtime continues sending validator-repair prompts, and control returns to the
local provider only after the repair sequence ends.
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
        "regressive semantic rewrite",
        "stopped making progress",
    )
    if any(marker in text for marker in strong_markers):
        return True
    return bool(
        re.search(r"\b(repair|fix|correct)\b", text)
        and re.search(r"\b(previous|failed|missing|invalid|incomplete|validator)\b", text)
    )


def _cloud_repair_prompt(prompt: str) -> str:
    """Strengthen a validator repair request without discarding its evidence."""
    return (
        "You are the expert rescue provider for an active validator-driven software repair.\n"
        "The local model failed repeatedly. Take ownership of this repair sequence until the "
        "artifact passes validation.\n\n"
        "MANDATORY OUTPUT RULES:\n"
        "- Return the complete corrected artifact requested by the runtime, not a summary, plan, patch note, or acknowledgement.\n"
        "- For browser work, return one complete self-contained HTML document beginning with <!doctype html> and ending with </html>.\n"
        "- Preserve all working behavior and make only the smallest changes needed for the validator failure.\n"
        "- Do not use Markdown fences. Do not return JSON unless the runtime explicitly asks for JSON.\n"
        "- Do not reply with phrases such as 'fixed', 'done', or 'here is the change' without the full artifact.\n\n"
        "ORIGINAL RUNTIME REPAIR REQUEST:\n"
        + str(prompt)
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
        active_rescue = str(getattr(self, "_quality_active_rescue", "") or "").strip().lower()

        # A non-repair call marks the end of the validator sequence. Only now is
        # control returned to the configured local provider.
        if not repair:
            if active_rescue:
                LOGGER.info(
                    "Validator repair sequence ended; returning from %s to %s",
                    active_rescue,
                    primary,
                )
            self._quality_active_rescue = ""
            self._quality_repair_streak = 0
            return original_generate(self, prompt, system_prompt)

        streak = int(getattr(self, "_quality_repair_streak", 0) or 0) + 1
        self._quality_repair_streak = streak

        threshold = 2
        try:
            cfg = fallback.load_llm_config()
            threshold = max(1, int(cfg.get("quality_escalation_after", 2) or 2))
            enabled = bool(cfg.get("allow_quality_escalation", True))
            preferred = str(cfg.get("quality_rescue_provider") or "").strip().lower()
        except Exception:  # noqa: BLE001
            enabled = True
            preferred = ""

        cloud = [
            (name, provider)
            for name, provider in getattr(self, "_providers", [])
            if name not in LOCAL_PROVIDER_IDS
        ]
        if preferred:
            cloud.sort(key=lambda item: item[0] != preferred)

        # Once rescue starts, keep the same provider for every subsequent repair
        # prompt. This prevents a valid cloud repair from being followed by more
        # low-quality local rewrites before validation can converge.
        should_rescue = enabled and cloud and (bool(active_rescue) or streak >= threshold)
        if should_rescue:
            errors: list[str] = []
            ordered = cloud
            if active_rescue:
                ordered = sorted(cloud, key=lambda item: item[0] != active_rescue)
            for name, provider in ordered:
                started = time.perf_counter()
                try:
                    text = provider.generate(_cloud_repair_prompt(prompt), system_prompt)
                except Exception as error:  # noqa: BLE001
                    errors.append(f"{name}: {type(error).__name__}: {error}")
                    LOGGER.warning("Quality rescue provider %s failed: %s", name, error)
                    continue

                elapsed_ms = (time.perf_counter() - started) * 1000
                self.last_provider = name
                self.last_errors = errors
                self.model = provider.model
                self._quality_active_rescue = name
                LOGGER.warning(
                    "Validator repair owned by %s in %.0fms; cloud rescue remains active until validation ends",
                    name,
                    elapsed_ms,
                )
                return text

            LOGGER.warning(
                "Configured quality rescue providers failed; continuing bounded local recovery: %s",
                "; ".join(errors),
            )

        return original_generate(self, prompt, system_prompt)

    fallback.resolve_provider_order = resolve_provider_order
    fallback.FallbackProvider.generate = generate
    fallback._quality_escalation_installed = True
