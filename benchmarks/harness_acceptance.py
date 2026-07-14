#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from sophyane.harness import AgentHarness, ContextManager, ModelRegistry, ToolRegistry, VerificationResult


def main() -> int:
    checks: dict[str, bool] = {}

    tools = ToolRegistry()
    tools.register("add", lambda left, right: left + right)
    checks["tool_registry"] = tools.invoke("add", left=20, right=22) == 42

    calls = {"broken": 0, "working": 0}

    def broken(prompt: str, system: str) -> str:
        calls["broken"] += 1
        raise RuntimeError("simulated outage")

    def working(prompt: str, system: str) -> str:
        calls["working"] += 1
        return "draft" if calls["working"] == 1 else "verified-answer=42"

    models = ModelRegistry()
    models.register("primary", broken, priority=1)
    models.register("fallback", working, priority=2)
    context = ContextManager(max_chars=180)
    harness = AgentHarness(models, tools=tools, context=context, max_iterations=3)

    result = harness.run(
        "Produce verified-answer=42",
        lambda output: VerificationResult(
            "verified-answer=42" in output,
            "output must contain verified-answer=42",
        ),
    )

    checks["model_registry_and_fallback"] = result.model == "fallback" and calls["broken"] >= 1
    checks["context_management"] = len(context.render()) <= 220
    checks["guardrails"] = not harness.guardrails.check_text("rm -rf /").allowed
    checks["agent_loop"] = result.iterations == 2
    checks["verification_steps"] = result.verified and sum(1 for item in result.trace if item["step"] == "verify") == 2

    passed = all(checks.values())
    output = Path("benchmark-results/harness")
    output.mkdir(parents=True, exist_ok=True)
    payload = {"passed": passed, "checks": checks, "result": {"verified": result.verified, "iterations": result.iterations, "model": result.model, "trace": result.trace}}
    (output / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Sophyane v13 harness acceptance",
        "",
        f"- Overall: **{'PASS' if passed else 'FAIL'}**",
        f"- Repair iterations: **{result.iterations}**",
        f"- Selected model: **{result.model}**",
        "",
        "| Capability | Result |",
        "|---|---:|",
    ]
    for name, value in checks.items():
        lines.append(f"| {name.replace('_', ' ').title()} | {'PASS' if value else 'FAIL'} |")
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
