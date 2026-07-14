#!/usr/bin/env python3
"""Offline acceptance checks for ten common LangGraph companion technologies."""

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
                "reason": "Live network calls are opt-in and require repository secrets.",
            }
    results["live_readiness"] = live

    passed = (
        bool(results["all_imported"])
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
        "- Live provider/service calls: **not claimed unless secrets are configured**",
        "",
        "| Software | Category | Import | Installed version | Live key/service |",
        "|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['package']} | {row['category']} | "
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
            f"- Sophyane multi-agent execution in integration environment: **{results['multiagent_with_adapter_environment']}**",
            f"- FastAPI local serving: **{results['fastapi_serving']}**",
            "",
            "PostgreSQL and Redis checks in this offline suite validate installation and public module imports. End-to-end database connectivity requires service containers and is tested separately when URLs are supplied.",
        ]
    )
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
