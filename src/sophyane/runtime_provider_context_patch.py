"""Truthful provider context and heartbeat reporting for interactive execution."""
from __future__ import annotations

import queue
import threading
import time
from typing import Any


def _provider_from_tui(tui: Any) -> Any:
    ask = getattr(tui, "ask", None)
    owner = getattr(ask, "__self__", None)
    provider = getattr(owner, "provider", None)
    if provider is not None:
        return provider
    return getattr(tui, "provider", None)


def _active_name(tui: Any) -> str:
    provider = _provider_from_tui(tui)
    if provider is not None:
        for attr in ("active_provider", "current_provider", "_quality_active_call_provider", "_quality_active_rescue", "last_provider"):
            value = str(getattr(provider, attr, "") or "").strip()
            if value:
                return value
        primary = str(getattr(provider, "primary", "") or "").strip()
        if primary:
            return primary
    return str(getattr(tui, "config", {}).get("provider") or "provider")


def install_provider_context_patch() -> None:
    from sophyane import tui_v2

    if getattr(tui_v2, "_provider_context_patch_installed", False):
        return

    def call_provider(self: Any, message: str, *, timeout: int = 60) -> Any:
        provider = _provider_from_tui(self)
        primary = str(getattr(provider, "primary", "") or self.config.get("provider") or "").lower()
        if primary in {"local_gguf", "ollama"}:
            timeout = max(timeout, 180)

        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        started = time.monotonic()
        self.last_prompt = message

        def worker() -> None:
            try:
                results.put(("ok", self.ask(message)))
            except Exception as error:  # noqa: BLE001
                results.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        next_update = 5
        announced = ""
        while True:
            try:
                status, value = results.get(timeout=1)
                self.last_elapsed = time.monotonic() - started
                if status == "error":
                    raise value
                used = _active_name(self)
                if used:
                    self.progress(f"Provider response received from {used} ({self.last_elapsed:.1f}s)")
                return value
            except queue.Empty:
                elapsed = int(time.monotonic() - started)
                active = _active_name(self)
                if active != announced:
                    mode = "cloud rescue" if active and active not in {"local_gguf", "ollama"} and primary in {"local_gguf", "ollama"} else "active"
                    self.progress(f"Provider: {active} ({mode})")
                    announced = active
                if elapsed >= next_update:
                    self.progress(f"Waiting for {active} response ({elapsed}s). Ctrl+C cancels.")
                    next_update += 5
                if elapsed >= timeout:
                    raise TimeoutError(f"{active} did not respond within {timeout}s.")

    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2._provider_context_patch_installed = True
