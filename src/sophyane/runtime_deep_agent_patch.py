"""Install deep-agent sandbox preparation and local-model timeout policy."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import re


def install_deep_agent_runtime() -> None:
    from sophyane.deep_agent_runtime import ensure_runtime_root, prepare_workspace

    ensure_runtime_root()

    try:
        from sophyane import tui_v2
    except ImportError:
        return

    if getattr(tui_v2, "_deep_agent_runtime_installed", False):
        return

    original_new_workspace = tui_v2.ObservableTUI._new_workspace
    original_call_provider = tui_v2.ObservableTUI.call_provider

    def new_workspace(self: Any) -> Path:
        request = str(getattr(self, "active_request", "") or "")

        # Honor an explicit autonomous benchmark/project workspace. This keeps
        # generated artifacts in the directory requested by the caller instead
        # of silently moving them under ~/.sophyane/workspaces.
        match = re.search(
            r"work exclusively inside\\s+(/[A-Za-z0-9_./~+@%=-]+)",
            request,
            flags=re.IGNORECASE,
        )

        if match:
            raw = match.group(1).rstrip(".,;:)")
            requested = Path(raw).expanduser().resolve()
            requested.mkdir(parents=True, exist_ok=True)
            workspace = requested
            self.progress(f"Using explicitly requested workspace: {workspace}")
        else:
            workspace = original_new_workspace(self)

        prepared = prepare_workspace(workspace, request=request)
        self.progress(f"Sandbox ready: {prepared}")
        return prepared

    def call_provider(self: Any, message: str, *, timeout: int = 60) -> Any:
        provider = str(getattr(self, "config", {}).get("provider") or "").strip().lower()
        effective = timeout
        if provider in {"local_gguf", "ollama"}:
            configured = int(getattr(self, "config", {}).get("timeout") or 0)
            effective = max(timeout, configured, 180)
            if effective != timeout:
                self.progress(f"Local generation timeout budget: {effective}s")
        return original_call_provider(self, message, timeout=effective)

    tui_v2.ObservableTUI._new_workspace = new_workspace
    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2._deep_agent_runtime_installed = True
