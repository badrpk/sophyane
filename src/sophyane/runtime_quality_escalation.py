"""Validator-triggered cloud rescue with sticky, truthful provider ownership."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from sophyane.provider_state import publish

LOGGER = logging.getLogger("sophyane")
LOCAL_PROVIDER_IDS = {"local_gguf", "ollama"}


def _is_repair_prompt(prompt: str) -> bool:
    text = " ".join(str(prompt or "").lower().split())
    markers = (
        "repairing incomplete", "previous response", "previous html", "validation failed",
        "validator", "failed verification", "missing required", "still missing",
        "no keyboard or touch controls", "return a corrected", "continue the same task",
        "regressive semantic rewrite", "stopped making progress", "continue immediately after",
        "truncated html",
    )
    return any(marker in text for marker in markers) or bool(
        re.search(r"\b(repair|fix|correct|continue)\b", text)
        and re.search(r"\b(previous|failed|missing|invalid|incomplete|validator|truncated)\b", text)
    )


def _cloud_repair_prompt(prompt: str) -> str:
    return (
        "You are the expert rescue provider for an active validator-driven software repair.\n"
        "Take ownership until the artifact passes validation.\n\n"
        "MANDATORY OUTPUT RULES:\n"
        "- Return the complete corrected artifact, not a summary or acknowledgement.\n"
        "- For browser work, return one complete HTML document ending with </html>.\n"
        "- Preserve working behavior and make the smallest valid changes.\n"
        "- Do not use Markdown fences.\n\n"
        "ORIGINAL RUNTIME REPAIR REQUEST:\n" + str(prompt)
    )


def install_quality_escalation() -> None:
    from sophyane.providers import fallback
    if getattr(fallback, "_quality_escalation_installed", False):
        return
    original_resolve = fallback.resolve_provider_order
    original_generate = fallback.FallbackProvider.generate

    def resolve_provider_order(primary: str, *, llm_config: dict[str, Any] | None = None) -> list[str]:
        cfg = llm_config if llm_config is not None else fallback.load_llm_config()
        primary_id = str(primary or "").strip().lower()
        order = original_resolve(primary_id, llm_config=cfg)
        if primary_id not in LOCAL_PROVIDER_IDS or not bool(cfg.get("allow_quality_escalation", True)):
            return order
        candidates = [cfg.get("quality_rescue_provider"), *(cfg.get("fallback_order", []) or []), *fallback.DEFAULT_FALLBACK_ORDER]
        for candidate in candidates:
            value = str(candidate or "").strip().lower()
            if value and value not in order and value not in {"fallback", *LOCAL_PROVIDER_IDS}:
                order.append(value)
        return order

    def set_active(self: Any, primary: str, active: str, mode: str) -> None:
        self.current_provider = active
        self.active_provider = active
        self._quality_active_call_provider = active
        publish(primary=primary, active=active, mode=mode)

    def generate(self: Any, prompt: str, system_prompt: str) -> str:
        primary = str(getattr(self, "primary", "") or "").strip().lower()
        set_active(self, primary, primary, "request")
        if primary not in LOCAL_PROVIDER_IDS:
            try:
                return original_generate(self, prompt, system_prompt)
            finally:
                used = str(getattr(self, "last_provider", "") or primary).lower()
                set_active(self, primary, used, "idle")

        repair = _is_repair_prompt(prompt)
        active_rescue = str(getattr(self, "_quality_active_rescue", "") or "").strip().lower()
        if not repair:
            if active_rescue:
                LOGGER.info("Validator repair sequence ended; returning from %s to %s", active_rescue, primary)
            self._quality_active_rescue = ""
            self._quality_repair_streak = 0
            set_active(self, primary, primary, "request")
            return original_generate(self, prompt, system_prompt)

        streak = int(getattr(self, "_quality_repair_streak", 0) or 0) + 1
        self._quality_repair_streak = streak
        try:
            cfg = fallback.load_llm_config()
            threshold = max(1, int(cfg.get("quality_escalation_after", 2) or 2))
            enabled = bool(cfg.get("allow_quality_escalation", True))
            preferred = str(cfg.get("quality_rescue_provider") or "").strip().lower()
        except Exception:  # noqa: BLE001
            threshold, enabled, preferred = 2, True, ""

        cloud = [(name, provider) for name, provider in getattr(self, "_providers", []) if name not in LOCAL_PROVIDER_IDS]
        if preferred:
            cloud.sort(key=lambda item: item[0] != preferred)
        if enabled and cloud and (active_rescue or streak >= threshold):
            errors: list[str] = []
            ordered = sorted(cloud, key=lambda item: item[0] != active_rescue) if active_rescue else cloud
            for name, provider in ordered:
                started = time.perf_counter()
                self._quality_active_rescue = name
                set_active(self, primary, name, "rescue")
                LOGGER.warning("Switching validator repair provider to %s", name)
                try:
                    text = provider.generate(_cloud_repair_prompt(prompt), system_prompt)
                except Exception as error:  # noqa: BLE001
                    errors.append(f"{name}: {type(error).__name__}: {error}")
                    LOGGER.warning("Quality rescue provider %s failed: %s", name, error)
                    continue
                self.last_provider = name
                self.last_errors = errors
                self.model = provider.model
                LOGGER.warning(
                    "Validator repair owned by %s in %.0fms; cloud rescue remains active until validation ends",
                    name, (time.perf_counter() - started) * 1000,
                )
                set_active(self, primary, name, "repair")
                return text
            LOGGER.warning("Configured quality rescue providers failed: %s", "; ".join(errors))
            self._quality_active_rescue = ""
            set_active(self, primary, primary, "repair")
        return original_generate(self, prompt, system_prompt)

    fallback.resolve_provider_order = resolve_provider_order
    fallback.FallbackProvider.generate = generate
    fallback._quality_escalation_installed = True
