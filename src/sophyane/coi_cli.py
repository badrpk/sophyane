from __future__ import annotations

import argparse
import json
from pathlib import Path

from sophyane.coi import AgentManifest, COIOrchestrator, TaskContract, status


def main() -> int:
    parser = argparse.ArgumentParser(prog="sophyane-coi", description="Sophyane Collaborative Orchestration Interface")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    task_parser = sub.add_parser("task")
    task_parser.add_argument("goal")
    task_parser.add_argument("--owner", default="supervisor")
    task_parser.add_argument("--workspace", default="")
    task_parser.add_argument("--repository", default="")
    task_parser.add_argument("--permission", action="append", default=[])
    agent_parser = sub.add_parser("agent-manifest")
    agent_parser.add_argument("name")
    agent_parser.add_argument("--role", required=True)
    agent_parser.add_argument("--skill", action="append", default=[])
    agent_parser.add_argument("--permission", action="append", default=[])
    agent_parser.add_argument("--tool", action="append", default=[])
    args = parser.parse_args()

    if args.command in {None, "status"}:
        print(json.dumps(status(), indent=2))
        return 0
    orchestrator = COIOrchestrator()
    if args.command == "task":
        task = TaskContract(goal=args.goal, owner=args.owner, workspace=args.workspace, repository=args.repository, permissions=args.permission)
        path = orchestrator.submit(task)
        print(json.dumps({"ok": True, "task_id": task.task_id, "path": str(path)}, indent=2))
        return 0
    if args.command == "agent-manifest":
        manifest = AgentManifest(name=args.name, role=args.role, skills=args.skill, permissions=args.permission, tools=args.tool)
        path = Path(orchestrator.paths["agents"]) / f"{manifest.name}.json"
        path.write_text(json.dumps({"name": manifest.name, "role": manifest.role, "skills": manifest.skills, "permissions": manifest.permissions, "tools": manifest.tools, "provider": manifest.provider, "max_steps": manifest.max_steps, "version": manifest.version}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "path": str(path)}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
