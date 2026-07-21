from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from sophyane.coi import AgentManifest, COIOrchestrator, TaskContract, status


def main() -> int:
    parser = argparse.ArgumentParser(prog="sophyane-coi", description="Sophyane Collaborative Orchestration Interface")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("queue")
    task_parser = sub.add_parser("task")
    task_parser.add_argument("goal")
    task_parser.add_argument("--owner", default="supervisor")
    task_parser.add_argument("--workspace", default="")
    task_parser.add_argument("--repository", default="")
    task_parser.add_argument("--priority", type=int, default=50)
    task_parser.add_argument("--timeout", type=int, default=300)
    task_parser.add_argument("--permission", action="append", default=[])
    task_parser.add_argument("--depends-on", action="append", default=[])
    task_parser.add_argument("--output", action="append", default=[])
    task_parser.add_argument("--validate", action="append", default=[])
    agent_parser = sub.add_parser("agent-manifest")
    agent_parser.add_argument("name")
    agent_parser.add_argument("--role", required=True)
    agent_parser.add_argument("--skill", action="append", default=[])
    agent_parser.add_argument("--permission", action="append", default=[])
    agent_parser.add_argument("--tool", action="append", default=[])
    agent_parser.add_argument("--provider", default="dispatcher")
    agent_parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()

    if args.command in {None, "status"}:
        print(json.dumps(status(), indent=2))
        return 0
    orchestrator = COIOrchestrator()
    if args.command == "queue":
        print(json.dumps({"ok": True, "tasks": orchestrator.queue()}, indent=2))
        return 0
    if args.command == "task":
        task = TaskContract(
            goal=args.goal,
            owner=args.owner,
            workspace=args.workspace,
            repository=args.repository,
            priority=max(0, min(100, args.priority)),
            timeout_seconds=max(1, args.timeout),
            permissions=args.permission,
            dependencies=args.depends_on,
            outputs=args.output,
            validation=args.validate,
        )
        path = orchestrator.submit(task)
        print(json.dumps({"ok": True, "task": asdict(task), "path": str(path)}, indent=2))
        return 0
    if args.command == "agent-manifest":
        manifest = AgentManifest(
            name=args.name,
            role=args.role,
            skills=args.skill,
            permissions=args.permission,
            tools=args.tool,
            provider=args.provider,
            max_steps=max(1, args.max_steps),
        )
        path = Path(orchestrator.paths["agents"]) / f"{manifest.name}.json"
        path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "manifest": asdict(manifest), "path": str(path)}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
