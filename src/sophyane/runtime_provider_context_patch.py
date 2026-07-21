"""Truthful provider dispatch context and heartbeat reporting."""
from __future__ import annotations

import queue
import threading
import time
from typing import Any

from sophyane.provider_state import publish, snapshot

_PROVIDER_ATTRS = ("provider", "llm", "backend", "dispatcher", "model_provider")
_STATE_ATTRS = ("_quality_active_call_provider", "active_provider", "current_provider", "_quality_active_rescue", "last_provider")


def _looks_like_provider(value: Any) -> bool:
    return value is not None and callable(getattr(value, "generate", None))


def _walk_provider(value: Any, seen: set[int] | None = None, depth: int = 0) -> Any:
    if value is None or depth > 6:
        return None
    seen = seen or set()
    marker = id(value)
    if marker in seen:
        return None
    seen.add(marker)
    if _looks_like_provider(value) and (hasattr(value, "_providers") or hasattr(value, "primary")):
        return value
    owner = getattr(value, "__self__", None)
    found = _walk_provider(owner, seen, depth + 1)
    if found is not None:
        return found
    for attr in _PROVIDER_ATTRS:
        try:
            child = getattr(value, attr, None)
        except Exception:  # noqa: BLE001
            child = None
        found = _walk_provider(child, seen, depth + 1)
        if found is not None:
            return found
    for cell in getattr(value, "__closure__", None) or ():
        try:
            child = cell.cell_contents
        except ValueError:
            continue
        found = _walk_provider(child, seen, depth + 1)
        if found is not None:
            return found
    return None


def _provider_from_tui(tui: Any) -> Any:
    cached = getattr(tui, "_sophyane_provider_dispatcher", None)
    if cached is not None:
        return cached
    provider = _walk_provider(getattr(tui, "ask", None)) or _walk_provider(tui)
    if provider is not None:
        tui._sophyane_provider_dispatcher = provider
    return provider


def _active_name(tui: Any) -> str:
    shared = snapshot()
    if shared.get("active") and shared.get("mode") in {"active", "repair", "rescue", "request"}:
        return str(shared["active"])
    provider = _provider_from_tui(tui)
    if provider is not None:
        for attr in _STATE_ATTRS:
            value = str(getattr(provider, attr, "") or "").strip().lower()
            if value:
                return value
        primary = str(getattr(provider, "primary", "") or "").strip().lower()
        if primary:
            return primary
    return str(getattr(tui, "config", {}).get("provider") or "provider").lower()


def install_provider_context_patch() -> None:
    from sophyane import tui_v2
    if getattr(tui_v2, "_provider_context_patch_installed", False):
        return
    original_init = tui_v2.ObservableTUI.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        provider = _walk_provider(getattr(self, "ask", None))
        if provider is not None:
            self._sophyane_provider_dispatcher = provider

    def call_provider(self: Any, message: str, *, timeout: int = 60) -> Any:
        provider = _provider_from_tui(self)
        primary = str(getattr(provider, "primary", "") or self.config.get("provider") or "").lower()
        publish(primary=primary, active=primary, mode="request")
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
                self.progress(f"Provider response received from {used} ({self.last_elapsed:.1f}s)")
                publish(primary=primary, active=used, mode="idle")
                return value
            except queue.Empty:
                elapsed = int(time.monotonic() - started)
                active = _active_name(self)
                if active != announced:
                    mode = "cloud rescue" if active not in {"local_gguf", "ollama"} and primary in {"local_gguf", "ollama"} else "active"
                    self.progress(f"Provider: {active} ({mode})")
                    announced = active
                if elapsed >= next_update:
                    self.progress(f"Waiting for {active} response ({elapsed}s). Ctrl+C cancels.")
                    next_update += 5
                if elapsed >= timeout:
                    publish(primary=primary, active=active, mode="timeout")
                    raise TimeoutError(f"{active} did not respond within {timeout}s.")

    tui_v2.ObservableTUI.__init__ = init
    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2._provider_context_patch_installed = True
