from __future__ import annotations

import argparse
import json
from pathlib import Path

from sophyane.engineering_program import ReleaseGate, program_status


def main() -> int:
    parser = argparse.ArgumentParser(prog="sophyane-release", description="Sophyane release and stabilization gate")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    gate = sub.add_parser("gate")
    gate.add_argument("path", nargs="?", default=".")
    gate.add_argument("--imports-only", action="store_true", help="Do not execute installed launcher commands")
    args = parser.parse_args()

    if args.command in {None, "status"}:
        result = program_status()
    else:
        report = ReleaseGate(Path(args.path)).run(execute_commands=not args.imports_only)
        result = report.to_dict()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
