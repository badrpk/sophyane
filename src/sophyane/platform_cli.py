"""Command-line access to the Sophyane platform kernel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sophyane.platform_kernel import AutoCompactor, EvaluationEngine, PromptAdvisor, RepositoryKernel, platform_status


def main() -> int:
    parser = argparse.ArgumentParser(prog="sophyane-platform")
    sub = parser.add_subparsers(dest="command", required=False)
    sub.add_parser("status")
    index = sub.add_parser("index")
    index.add_argument("path", nargs="?", default=".")
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("path", nargs="?", default=".")
    compact = sub.add_parser("compact")
    compact.add_argument("path", nargs="?", default=str(Path.home() / ".sophyane"))
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("path", nargs="?", default=".")
    advise = sub.add_parser("advise")
    advise.add_argument("prompt", nargs="+")
    args = parser.parse_args()

    command = args.command or "status"
    if command == "status":
        result = platform_status()
    elif command == "index":
        result = RepositoryKernel(Path(args.path)).index()
    elif command == "checkpoint":
        result = RepositoryKernel(Path(args.path)).checkpoint().__dict__
    elif command == "compact":
        result = AutoCompactor().compact(Path(args.path))
    elif command == "eval":
        result = EvaluationEngine().evaluate(Path(args.path)).__dict__
    elif command == "advise":
        prompt = " ".join(args.prompt)
        result = {"prompt": prompt, "advice": PromptAdvisor.advise(prompt), "template": PromptAdvisor.TEMPLATE}
    else:
        result = {"ok": False, "error": f"unknown command: {command}"}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
