"""SLI-managed quality escalation with truthful provider ownership."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from sophyane.provider_state import publish
from sophyane.sli_provider_controller import get_sli_provider_controller

LOGGER = logging.getLogger("sophyane")
LOCAL_PROVIDER_IDS = {"local_gguf", "ollama"}


def _is_repair_prompt(prompt: str) -> bool:
    text = " ".join(str(prompt or "").lower().split())
    markers = (
        "repairing incomplete", "previous response", "previous html", "validation failed",
        "validator", "failed verification", "missing required", "still missing",
        "no keyboard or touch controls", "return a corrected", "continue the same task",
        "regressive semantic rewrite", "stopped making progress", "continue immediately after",
        "truncated html", "game artifact contains no javascript", "closing </html> was missing",
    )
    return any(marker in text for marker in markers) or bool(
        re.search(r"\b(repair|fix|correct|continue)\b", text)
        and re.search(r"\b(previous|failed|missing|invalid|incomplete|validator|truncated)\b", text)
    )


def _cloud_repair_prompt(prompt: str, local_response: str = "", defects: list[str] | None = None) -> str:
    evidence = ""
    if local_response:
        evidence = (
            "\n\nLOCAL ARTIFACT TO REPAIR OR REPLACE:\n"
            + local_response[-12000:]
        )
    defect_text = ", ".join(defects or []) or "validator or SLI quality failure"
    return (
        "You are the expert rescue provider for an active SLI-managed software repair.\n"
        "Take ownership until the artifact passes validation.\n\n"
        "MANDATORY OUTPUT RULES:\n"
        "- Return the complete corrected artifact, not a summary or acknowledgement.\n"
        "- For browser work, return complete self-contained HTML beginning with "
        "<!doctype html> and ending with </html>.\n"
        "- Interactive games must include working JavaScript and keyboard/touch interaction.\n"
        "- Preserve working behaviour where possible, but replace an irreparable partial artifact.\n"
        "- Do not use Markdown fences.\n\n"
        f"SLI-DETECTED DEFECTS: {defect_text}\n\n"
        "ORIGINAL RUNTIME REQUEST:\n" + str(prompt) + evidence
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

    def cloud_candidates(self: Any, preferred: str = "", active_rescue: str = "") -> list[tuple[str, Any]]:
        cloud = [(name, provider) for name, provider in getattr(self, "_providers", []) if name not in LOCAL_PROVIDER_IDS]
        target = active_rescue or preferred
        if target:
            cloud.sort(key=lambda item: item[0] != target)
        return cloud

    def run_cloud_rescue(
        self: Any,
        *,
        primary: str,
        prompt: str,
        system_prompt: str,
        local_response: str = "",
        defects: list[str] | None = None,
        preferred: str = "",
        active_rescue: str = "",
    ) -> str | None:
        errors: list[str] = []
        for name, provider in cloud_candidates(self, preferred, active_rescue):
            started = time.perf_counter()
            self._quality_active_rescue = name
            set_active(self, primary, name, "sli_rescue")
            LOGGER.warning("SLI switching artifact provider from %s to %s", primary, name)
            try:
                text = provider.generate(_cloud_repair_prompt(prompt, local_response, defects), system_prompt)
            except Exception as error:  # noqa: BLE001
                errors.append(f"{name}: {type(error).__name__}: {error}")
                LOGGER.warning("SLI rescue provider %s failed: %s", name, error)
                continue
            self.last_provider = name
            self.last_errors = errors
            self.model = provider.model
            LOGGER.warning(
                "SLI rescue owned by %s in %.0fms; rescue remains sticky through this repair sequence",
                name, (time.perf_counter() - started) * 1000,
            )
            set_active(self, primary, name, "repair")
            return text
        if errors:
            LOGGER.warning("Configured SLI rescue providers failed: %s", "; ".join(errors))
        self._quality_active_rescue = ""
        set_active(self, primary, primary, "repair")
        return None

    def generate(self: Any, prompt: str, system_prompt: str) -> str:
        primary = str(getattr(self, "primary", "") or "").strip().lower()
        set_active(self, primary, primary, "request")
        if primary not in LOCAL_PROVIDER_IDS:
            try:
                return original_generate(self, prompt, system_prompt)
            finally:
                used = str(getattr(self, "last_provider", "") or primary).lower()
                set_active(self, primary, used, "idle")

        controller = get_sli_provider_controller()
        repair = _is_repair_prompt(prompt)
        active_rescue = str(getattr(self, "_quality_active_rescue", "") or "").strip().lower()
        try:
            cfg = fallback.load_llm_config()
            enabled = bool(cfg.get("allow_quality_escalation", True))
            preferred = str(cfg.get("quality_rescue_provider") or "").strip().lower()
        except Exception:  # noqa: BLE001
            enabled, preferred = True, ""

        # Give the configured local provider exactly one bounded repair
        # attempt. On the next repair request, transfer ownership to cloud
        # before calling local again, so a useful local reply is not consumed
        # and discarded during escalation.
        prior_repair_streak = int(
            getattr(self, "_quality_repair_streak", 0) or 0
        )
        if (
            repair
            and enabled
            and not active_rescue
            and prior_repair_streak >= 1
        ):
            rescued = run_cloud_rescue(
                self,
                primary=primary,
                prompt=prompt,
                system_prompt=system_prompt,
                preferred=preferred,
            )
            if rescued is not None:
                return rescued

        # Once SLI has transferred ownership during a repair sequence, keep the
        # rescue provider active until a new non-repair request begins.
        if repair and enabled and active_rescue:
            rescued = run_cloud_rescue(
                self,
                primary=primary,
                prompt=prompt,
                system_prompt=system_prompt,
                preferred=preferred,
                active_rescue=active_rescue,
            )
            if rescued is not None:
                return rescued

        if not repair and active_rescue:
            LOGGER.info("SLI repair sequence ended; returning from %s to %s", active_rescue, primary)
            self._quality_active_rescue = ""
            self._quality_repair_streak = 0
            controller.reset_sequence()
        elif not repair:
            self._quality_repair_streak = 0

        started = time.perf_counter()
        set_active(self, primary, primary, "request")
        local_text = original_generate(self, prompt, system_prompt)
        latency = time.perf_counter() - started
        decision = controller.observe(
            prompt=prompt,
            response=local_text,
            latency_seconds=latency,
            provider=primary,
        )
        repair_streak = int(
            getattr(self, "_quality_repair_streak", 0) or 0
        )
        if repair and decision.defects:
            repair_streak += 1
        elif not repair:
            repair_streak = 0
        self._quality_repair_streak = repair_streak

        LOGGER.info(
            "SLI provider decision=%s risk=%.3f confidence=%.3f defects=%s",
            decision.action,
            decision.risk,
            decision.confidence,
            ",".join(decision.defects) or "none",
        )

        # Always allow one bounded local repair before transferring
        # ownership to a cloud rescue provider. Subsequent repair calls remain
        # sticky with the selected rescue provider until a non-repair request.
        should_escalate = (
            enabled
            and decision.action == "escalate_cloud"
            and (not repair or repair_streak >= 2)
        )

        if should_escalate:
            rescued = run_cloud_rescue(
                self,
                primary=primary,
                prompt=prompt,
                system_prompt=system_prompt,
                local_response=local_text,
                defects=decision.defects,
                preferred=preferred,
            )
            if rescued is not None:
                return rescued

        self.last_provider = primary
        set_active(self, primary, primary, "repair" if decision.defects else "idle")
        return local_text

    fallback.resolve_provider_order = resolve_provider_order
    fallback.FallbackProvider.generate = generate
    fallback._quality_escalation_installed = True
