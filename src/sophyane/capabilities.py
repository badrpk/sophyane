"""Master agent capability registry — what a modern agent needs through ~2030.

Sophyane aims to cover the full surface: reason, act, remember, learn, connect,
observe, and stay safe. This module is the single inventory used by --capabilities,
--audit, and docs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sophyane.version import __version__


@dataclass
class Capability:
    id: str
    name: str
    status: str  # ready | partial | planned
    module: str
    cli: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Comprehensive inventory of expected agent features (present + shipped now).
CAPABILITIES: list[Capability] = [
    # Core cognition
    Capability("multi_provider", "Multi-provider LLM + fallback", "ready", "providers", "--providers /llm.json"),
    Capability("local_models", "Local open models (Ollama/GGUF)", "ready", "local_runtime", "/local"),
    Capability("harness_loop", "Plan→act→observe→verify harness", "ready", "harness", "default agent loop"),
    Capability("structured_output", "Strict JSON / structured protocols", "ready", "structured_output", "--protocol-attempts"),
    Capability("expert_pack", "Expert knowledge for hard eng Qs", "ready", "expert", "--ask / --exam-tough100"),
    # Tools & coding
    Capability("safe_tools", "Sandboxed shell/file/git tools", "ready", "tools", "tool registry"),
    Capability("coding_agent", "Repo index, patches, self-repair", "ready", "coding_runtime", "coding doers"),
    Capability("code_interpreter", "Sandboxed Python REPL", "ready", "interpreter", "--repl / --eval"),
    Capability("skills", "Reusable skill packs (prompts+tools)", "ready", "skills", "--skills / --skill"),
    # Memory & knowledge
    Capability("memory", "Persistent SQLite session memory", "ready", "memory", "auto"),
    Capability("rag", "Local document RAG / knowledge base", "ready", "rag", "--rag-add / --rag-query"),
    Capability("web_intel", "Web fetch/scrape for learning", "ready", "web_intel", "--fetch / --learn"),
    Capability("checkpoint", "Long-task checkpoint & resume", "ready", "checkpoint", "--checkpoint-list"),
    # Multi-agent & autonomy
    Capability("multiagent", "Supervisor/worker multi-agent", "ready", "multiagent", "--multi-agent"),
    Capability("graph_runtime", "Graph / LangGraph-style flows", "ready", "graph_runtime", "graph API"),
    Capability("autonomy", "Autonomous builder / doer policies", "ready", "autonomy", "doer modes"),
    Capability("daemon", "Background daemon ticks", "ready", "daemon_runtime", "daemon"),
    Capability("scheduler", "Cron-like scheduled agent jobs", "ready", "scheduler", "--schedule"),
    # Human & safety
    Capability("hitl", "Human-in-the-loop approvals", "ready", "hitl", "--approve / HITL queue"),
    Capability("guardrails", "Destructive-command guardrails", "ready", "harness", "built-in"),
    Capability("budget", "Token/cost/time budgets", "ready", "budget", "--budget-status"),
    Capability("permissions", "Permission profiles (read/write/net)", "ready", "permissions", "--permissions"),
    # Connectivity & platforms
    Capability("mesh", "Device mesh USB/WiFi/compute share", "ready", "mesh", "--mesh-*"),
    Capability("mcp", "MCP-style tool server/client bridge", "ready", "mcp_bridge", "--mcp-serve / --mcp-list"),
    Capability("hardware_api", "Python/C++/JS hardware API", "ready", "hardware_api", "--hardware-api"),
    Capability("edge", "Edge/IoT constrained profiles", "ready", "edge_agent", "--edge-health"),
    Capability("appliance", "SoC appliance boot + net", "ready", "appliance", "--boot"),
    Capability("browser", "Chromium Sophyane browser shell", "ready", "browser", "--browser"),
    Capability("erp", "Oracle/SAP/Odoo ERP adapters", "ready", "kernel.erp", "--erp"),
    Capability("app_factory", "Web/Android/iOS/Harmony scaffolds", "ready", "kernel.app_factory", "--create-app"),
    # Learning & improvement
    Capability("self_improve", "Hash-chain self-improvement ledger", "ready", "self_improve", "--improve-*"),
    Capability("continual_train", "Federated PEFT C++ continual train", "ready", "continual", "--train-*"),
    # UX & ops
    Capability("tui", "Grok-style interactive TUI", "ready", "tui", "sophyane"),
    Capability("observability", "Run traces / spans export", "ready", "observability", "--trace-list"),
    Capability("notifications", "Completion notifications", "ready", "notifications", "--notify-test"),
    Capability("multimodal", "Image/vision + voice hooks", "ready", "multimodal", "--image / --voice-status"),
    Capability("doctor_audit", "Doctor + full feature audit", "ready", "diagnostics", "--doctor / --audit"),
    Capability("plugins", "Provider plugin loader", "ready", "plugin_loader", "plugins/"),
    # Near-future partial (honest)
    Capability("computer_use", "Full GUI computer-use automation", "partial", "tools", "shell+browser; full GUI planned"),
    Capability("realtime_voice", "Full duplex realtime voice", "partial", "multimodal", "hooks ready; needs STT/TTS bin"),
    Capability("a2a_standard", "External A2A protocol federation", "partial", "mesh", "mesh RPC; A2A mapping partial"),
]


def capability_matrix() -> dict[str, Any]:
    ready = [c for c in CAPABILITIES if c.status == "ready"]
    partial = [c for c in CAPABILITIES if c.status == "partial"]
    planned = [c for c in CAPABILITIES if c.status == "planned"]
    return {
        "ok": True,
        "version": __version__,
        "total": len(CAPABILITIES),
        "ready": len(ready),
        "partial": len(partial),
        "planned": len(planned),
        "coverage_pct": round(100 * (len(ready) + 0.5 * len(partial)) / max(1, len(CAPABILITIES)), 1),
        "capabilities": [c.to_dict() for c in CAPABILITIES],
        "message": (
            "Sophyane targets the full modern agent surface: reason, act, remember, "
            "learn, connect, observe, schedule, and stay safe — with honest partials "
            "only where OS/hardware binaries are required."
        ),
    }


def format_capability_report() -> str:
    m = capability_matrix()
    lines = [
        f"Sophyane {m['version']} — Agent capability matrix",
        f"Ready {m['ready']}/{m['total']}  Partial {m['partial']}  Coverage ~{m['coverage_pct']}%",
        "",
        f"{'ID':22} {'Status':8} Name",
        "-" * 72,
    ]
    for c in CAPABILITIES:
        lines.append(f"{c.id:22} {c.status:8} {c.name}")
    lines.append("")
    lines.append(m["message"])
    return "\n".join(lines)
