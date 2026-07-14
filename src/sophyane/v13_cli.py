"""Sophyane v13 CLI with automatic supervisor-worker routing."""

from __future__ import annotations

import argparse
import json

from sophyane.agent import SophyaneAgent
from sophyane.autonomy import AUTONOMOUS_WORKER_POLICY
from sophyane.config import ensure_directories
from sophyane.diagnostics import run_diagnostics
from sophyane.logging_config import configure_logging
from sophyane.main import (
    create_provider,
    handle_internal_command,
    interactive,
    list_providers,
    load_runtime_config,
    show_status,
)
from sophyane.memory import MemoryStore
from sophyane.multiagent import MultiAgentRuntime, MultiAgentStore
from sophyane.setup_wizard import run_setup_wizard
from sophyane.structured_output import (
    StructuredOutputError,
    render_strict_json,
    requests_strict_json,
)
from sophyane.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane",
        description=(
            "Sophyane v13 local AI runtime with durable graphs, memory and "
            "real supervisor-worker multi-agent execution."
        ),
    )
    parser.add_argument("prompt", nargs="*", help="prompt to process")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--providers", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--single-agent", action="store_true", help="force one worker")
    parser.add_argument("--multi-agent", action="store_true", help="force supervisor-worker execution")
    parser.add_argument("--agent-json", action="store_true", help="print complete machine-readable run metadata")
    parser.add_argument("--inspect-run", metavar="RUN_ID", help="inspect a persisted multi-agent run")
    parser.add_argument("--max-workers", type=int, default=6, help="maximum concurrent worker agents")
    parser.add_argument("--agent-attempts", type=int, default=2, help="attempts per worker")
    parser.add_argument(
        "--approval-timeout",
        type=float,
        default=10.0,
        help="seconds before safe scoped actions auto-continue (default: 10)",
    )
    parser.add_argument(
        "--no-auto-continue",
        action="store_true",
        help="disable timeout auto-continuation for safe actions",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _execution_policy(timeout: float, enabled: bool) -> str:
    if not enabled:
        return (
            AUTONOMOUS_WORKER_POLICY
            + "\nTimeout auto-continuation is disabled for this invocation; "
            "safe actions still require an explicit response."
        )
    return AUTONOMOUS_WORKER_POLICY.replace("10 seconds", f"{max(0.0, timeout):g} seconds")


def main() -> int:
    ensure_directories()
    parser = build_parser()
    args = parser.parse_args()
    logger = configure_logging(args.verbose)

    if args.single_agent and args.multi_agent:
        parser.error("--single-agent and --multi-agent cannot be used together")

    store = MultiAgentStore()
    if args.inspect_run:
        run = store.inspect_run(args.inspect_run)
        if run is None:
            print(json.dumps({"status": "not_found", "run_id": args.inspect_run}))
            return 1
        print(json.dumps(run, indent=2, ensure_ascii=False))
        return 0

    if args.doctor:
        passed, report = run_diagnostics()
        print(report)
        return 0 if passed else 1
    if args.providers:
        print(list_providers())
        return 0

    config = run_setup_wizard() if args.setup else load_runtime_config()
    if args.status:
        print(show_status(config))
        return 0
    if not args.prompt:
        return interactive(config, args.verbose)

    original_prompt = " ".join(args.prompt)
    memory = MemoryStore()
    provider = create_provider(config)

    # Preserve internal commands and strict compatibility behavior.
    agent = SophyaneAgent(provider, memory, logger)
    if original_prompt.startswith("/"):
        response = agent.ask(original_prompt)
        if response.text.startswith("INTERNAL_COMMAND:"):
            command = response.text.split(":", 1)[1]
            text, _ = handle_internal_command(command, config)
            print(text)
        else:
            print(response.text)
        return 0

    mode = "multi" if args.multi_agent else "single" if args.single_agent else "auto"
    policy = _execution_policy(args.approval_timeout, not args.no_auto_continue)

    def autonomous_backend(prompt: str, system: str) -> str:
        combined_system = (system + "\n\n" + policy).strip()
        return provider.generate(prompt, combined_system)

    runtime = MultiAgentRuntime(
        backend=autonomous_backend,
        store=store,
        max_workers=args.max_workers,
        max_attempts=args.agent_attempts,
    )
    result = runtime.run(original_prompt, mode=mode)

    if args.agent_json:
        payload = result.to_dict()
        payload["autonomy"] = {
            "safe_auto_continue": not args.no_auto_continue,
            "approval_timeout_seconds": max(0.0, args.approval_timeout),
            "dangerous_actions_auto_approved": False,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if result.final_output else 2

    if requests_strict_json(original_prompt):
        try:
            print(render_strict_json(original_prompt, result.final_output))
            return 0
        except StructuredOutputError as error:
            logger.error("Strict JSON contract failed: %s", error)
            print(
                '{"status":"failed","error":"strict_json_contract",'
                '"message":"workers returned no valid JSON"}'
            )
            return 2

    print(
        f"EXECUTION_MODE={result.mode}\n"
        f"AGENT_COUNT={len(result.workers)}\n"
        f"ACTUAL_WORKERS_LAUNCHED={len(result.workers)}\n"
        f"SUPERVISOR_ID={result.supervisor_id}\n"
        f"RUN_ID={result.run_id}\n"
        f"SAFE_AUTO_CONTINUE={'true' if not args.no_auto_continue else 'false'}\n"
        f"APPROVAL_TIMEOUT_SECONDS={max(0.0, args.approval_timeout):g}\n"
        "AGENT_ROLES=" + ",".join(worker.role for worker in result.workers)
    )
    print()
    print(result.final_output)
    return 0 if result.final_output else 2


if __name__ == "__main__":
    raise SystemExit(main())
