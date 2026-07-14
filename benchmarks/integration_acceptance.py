#!/usr/bin/env python3
"""Offline acceptance checks for Sophyane's 30 ecosystem targets."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda

from sophyane.integrations import InvokeAdapter, probe_integrations
from sophyane.multiagent import MultiAgentRuntime, MultiAgentStore


class EchoProvider:
    def generate(self, prompt: str, system_prompt: str) -> str:
        return f"{system_prompt}\n{prompt}"


def main() -> int:
    rows = probe_integrations()
    results: dict[str, object] = {
        "offline_imports": rows,
        "target_count": len(rows),
        "base_count": sum(row.get("tier") == "base" for row in rows),
        "extended_count": sum(row.get("tier") == "extended" for row in rows),
        "all_imported": all(row["installed"] for row in rows),
    }

    runnable = RunnableLambda(lambda value: f"lc:{value}")
    adapter = InvokeAdapter(runnable)
    results["langchain_runnable_adapter"] = adapter.generate("hello", "") == "lc:hello"

    with tempfile.TemporaryDirectory() as temp:
        provider = EchoProvider()
        store = MultiAgentStore(Path(temp) / "agents.db")
        runtime = MultiAgentRuntime(
            lambda prompt, system_prompt: provider.generate(prompt, system_prompt),
            store=store,
            max_workers=5,
        )
        report = runtime.run(
            "Build an API with database, tests, security and documentation",
            mode="multi",
        )
        persisted = store.inspect_run(report.run_id)
        results["multiagent_with_adapter_environment"] = (
            report.mode == "multi_agent"
            and len(report.workers) > 1
            and persisted is not None
            and len(persisted["workers"]) == len(report.workers)
        )

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    results["fastapi_serving"] = client.get("/health").json() == {"ok": True}

    live = {}
    for row in rows:
        variable = row.get("live_environment")
        if variable:
            live[row["key"]] = {
                "configured": bool(os.environ.get(str(variable))),
                "executed": False,
                "reason": "Live network/service calls are opt-in and require credentials or a reachable service.",
            }
    results["live_readiness"] = live

    passed = (
        bool(results["all_imported"])
        and len(rows) == 30
        and bool(results["langchain_runnable_adapter"])
        and bool(results["multiagent_with_adapter_environment"])
        and bool(results["fastapi_serving"])
    )
    results["passed"] = passed

    output = Path("benchmark-results/integrations")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )

    lines = [
        "# Sophyane v13 ecosystem compatibility",
        "",
        f"- Offline acceptance: **{'PASS' if passed else 'FAIL'}**",
        f"- Targets tested: **{len(rows)}** (10 base + 20 extended)",
        "- Live provider/service calls: **not claimed unless credentials or services are configured**",
        "",
        "| Software | Tier | Category | Import | Installed version | Live key/service |",
        "|---|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['package']} | {row.get('tier', 'base')} | {row['category']} | "
            f"{'PASS' if row['installed'] else 'FAIL'} | "
            f"{row.get('version', row.get('error', 'unknown'))} | "
            f"{row.get('live_environment') or 'not required'} |"
        )
    lines.extend(
        [
            "",
            "## Adapter checks",
            "",
            f"- LangChain Runnable → Sophyane backend: **{results['langchain_runnable_adapter']}**",
            f"- Sophyane multi-agent execution in 30-package environment: **{results['multiagent_with_adapter_environment']}**",
            f"- FastAPI local serving: **{results['fastapi_serving']}**",
            "",
            "Import checks prove package and public-module compatibility. Hosted providers, vector databases, queues and telemetry backends require separate live tests before live-operation claims are made.",
        ]
    )
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
