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


def _sli_handler(plan: ModePlan, _capability: object) -> Any:
    from sophyane.sli_semantic_intelligence import build_semantic_plan

    return build_semantic_plan(plan.payload.get("text", ""))


def _race_handler(plan: ModePlan, _capability: object) -> Any:
    from sophyane.config import load_config
    from sophyane.race_orchestrator import run_adaptive_race

    return run_adaptive_race(
        plan.payload.get("text", ""),
        workspace=Path.cwd(),
        config=load_config(),
    )


def _learning_handler(plan: ModePlan, capability: object) -> Any:
    from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource, autonomous_bus

    evidence = plan.payload.get("evidence")
    if evidence is None:
        context = plan.payload.get("context", {})
        evidence = context.get("evidence", {}) if isinstance(context, dict) else {}
    if isinstance(evidence, dict):
        values = evidence
    else:
        values = {"value": evidence}
    problem = str(values.get("problem") or plan.payload.get("text") or "runtime learning observation")
    component = str(values.get("component") or "sophyane.core_controller")
    raw_evidence = values.get("evidence") or (str(values.get("value") or "observed"),)
    if isinstance(raw_evidence, str):
        raw_evidence = (raw_evidence,)
    observation = ImprovementObservation(
        source=ImprovementSource.RUNTIME,
        problem=problem,
        component=component,
        evidence=tuple(str(item) for item in raw_evidence),
        suggested_direction=str(values.get("suggested_direction") or ""),
    )
    accepted = autonomous_bus.submit(observation)
    from .curriculum_bridge import default_curriculum_bridge

    task_enqueued, task_id = default_curriculum_bridge().enqueue_observation(observation)
    return {
        "accepted": accepted,
        "fingerprint": observation.fingerprint,
        "task_enqueued": task_enqueued,
        "task_id": task_id,
    }


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
        ModeName.RACE: {
            "provider": "local_gguf",
            "ready": local_ready,
            "handler": _race_handler,
        },
        ModeName.SLI_GRAPH: {
            "provider": "local_gguf",
            "ready": local_ready,
            "handler": _sli_handler,
        },
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
        ModeName.LEARNING: {
            "provider": "local_gguf",
            "ready": local_ready,
            "handler": _learning_handler,
        },
    }


__all__ = ["build_host_dependencies"]
