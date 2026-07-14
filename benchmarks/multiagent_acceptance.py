#!/usr/bin/env python3
"""Offline acceptance test proving Sophyane v13 creates real worker instances."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from sophyane.multiagent import MultiAgentRuntime, MultiAgentStore


class Backend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.lock = threading.Lock()

    def __call__(self, prompt: str, system_prompt: str) -> str:
        with self.lock:
            self.calls.append(
                {
                    "thread_id": threading.get_ident(),
                    "system_prompt": system_prompt,
                    "started": time.time(),
                }
            )
        time.sleep(0.03)
        return "PASS: role completed objective and validation"


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="sophyane-v13-acceptance-"))
    backend = Backend()
    store = MultiAgentStore(root / "multiagent.db")
    runtime = MultiAgentRuntime(backend, store=store, max_workers=6)

    simple = runtime.run("Fix one Python syntax error", mode="auto")
    complex_run = runtime.run(
        "Build a complete backend API with authentication, database, security "
        "review, tests, Docker deployment and documentation",
        mode="auto",
    )
    forced = runtime.run("Implement and test a calculator", mode="multi")

    worker_threads = {int(call["thread_id"]) for call in backend.calls}
    complex_worker_ids = {worker.worker_id for worker in complex_run.workers}
    persisted = store.inspect_run(complex_run.run_id)

    checks = {
        "simple_routes_single": simple.mode == "single_agent" and len(simple.workers) == 1,
        "complex_routes_multi": complex_run.mode == "multi_agent" and len(complex_run.workers) >= 5,
        "forced_multi": forced.mode == "multi_agent" and len(forced.workers) >= 3,
        "unique_worker_ids": len(complex_worker_ids) == len(complex_run.workers),
        "parallel_threads": len(worker_threads) > 1,
        "supervisor_present": complex_run.supervisor_id.startswith("supervisor-"),
        "workers_persisted": persisted is not None and len(persisted["workers"]) == len(complex_run.workers),
        "lifecycle_events": any(event["event_type"] == "workers_launched" for event in complex_run.trace),
        "reviewer_completed": complex_run.workers[-1].role == "reviewer" and complex_run.workers[-1].status == "completed",
        "final_output": bool(complex_run.final_output),
    }
    passed = all(checks.values())
    report = {
        "classification": "B" if passed else "NOT_VERIFIED",
        "label": "true coordinated multi-agent runtime" if passed else "acceptance failure",
        "checks": checks,
        "simple": simple.to_dict(),
        "complex": complex_run.to_dict(),
        "forced_multi": forced.to_dict(),
        "backend_thread_ids": sorted(worker_threads),
        "database": str(store.path),
    }
    output = Path("benchmark-results/multiagent-v13")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Sophyane v13 multi-agent acceptance",
        "",
        f"- Classification: **{report['classification']} — {report['label']}**",
        f"- Unique execution threads: **{len(worker_threads)}**",
        f"- Complex-run workers: **{len(complex_run.workers)}**",
        f"- Run ID: `{complex_run.run_id}`",
        f"- Supervisor ID: `{complex_run.supervisor_id}`",
        "",
        "| Check | Result |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {'PASS' if value else 'FAIL'} |" for name, value in checks.items())
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((output / "REPORT.md").read_text(encoding="utf-8"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
