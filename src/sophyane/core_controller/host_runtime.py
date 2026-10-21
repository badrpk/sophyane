"""Explicit bindings for dependencies that are locally provable at runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import ModeName, ModePlan


def _local_handler(plan: ModePlan, _capability: object) -> Any:
    from sophyane.providers.local_gguf import LocalGgufProvider

    return LocalGgufProvider().generate(plan.payload.get("text", ""), "Sophyane local mode")


def _codex_handler(plan: ModePlan, capability: object) -> Any:
    from sophyane.providers.codex_cli import CodexCliProvider

    workspace = Path.cwd()
    if isinstance(capability, dict) and capability.get("workspace"):
        workspace = Path(str(capability["workspace"])).expanduser().resolve()
    return CodexCliProvider(workspace=workspace).generate(
        plan.payload.get("text", ""),
        "Sophyane external mode; return evidence, never claim execution.",
    )


def _conversation_handler(plan: ModePlan, _capability: object) -> Any:
    from sophyane.human_conversation import conversation_turn

    return conversation_turn(plan.payload.get("text", ""))


def build_host_dependencies() -> dict[ModeName, dict[str, Any]]:
    """Return explicit, readiness-backed host bindings.

    Race, SLI, and learning remain unavailable until their state/workspace
    contracts are supplied by their dedicated orchestrators. This factory
    never launches Chromium or changes a browser profile as a side effect.
    """
    from sophyane.local_runtime import llama_server_reachable
    from sophyane.providers.codex_cli import agy_available

    local_ready = lambda: bool(llama_server_reachable())
    codex_ready = lambda: bool(agy_available())
    return {
        ModeName.LOCAL_LLM: {
            "provider": "local_gguf",
            "ready": local_ready,
            "handler": _local_handler,
        },
        ModeName.EXTERNAL_LLM: {
            "provider": "codex_cli",
            "ready": codex_ready,
            "handler": _codex_handler,
        },
        ModeName.HUMAN_CONVERSATION: {
            "provider": "codex_cli",
            "ready": codex_ready,
            "handler": _conversation_handler,
        },
    }


__all__ = ["build_host_dependencies"]
