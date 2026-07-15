"""Sophyane v16 CLI: repository-aware coding execution by default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sophyane.agent import SophyaneAgent
from sophyane.autonomy import AUTONOMOUS_WORKER_POLICY
from sophyane.config import ensure_directories
from sophyane.diagnostics import run_diagnostics
from sophyane.live_coding_doer import LiveProgressReporter
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
from sophyane.strict_interactive_doer import StrictInteractiveCodingDoerRuntime
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
            "Sophyane v16 repository-aware coding agent with semantic indexing, "
            "precise patches, batched tools, self-repair and deterministic verification."
        ),
    )
    parser.add_argument("prompt", nargs="*", help="prompt to process")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--providers", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--single-agent", action="store_true", help="use legacy one-worker runtime")
    parser.add_argument("--multi-agent", action="store_true", help="use legacy supervisor-worker runtime")
    parser.add_argument("--agent-json", action="store_true", help="print complete machine-readable run metadata")
    parser.add_argument("--inspect-run", metavar="RUN_ID", help="inspect a persisted legacy multi-agent run")
    parser.add_argument("--max-workers", type=int, default=6, help="maximum legacy concurrent workers")
    parser.add_argument("--agent-attempts", type=int, default=2, help="attempts per legacy worker")
    parser.add_argument("--max-steps", type=int, default=16, help="maximum planner-executor-verifier cycles")
    parser.add_argument(
        "--workspace",
        default=".",
        help="repository or directory in which approved edits and commands execute",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable live operational progress messages",
    )
    parser.add_argument(
        "--progress-heartbeat",
        type=float,
        default=5.0,
        help="seconds between progress heartbeats during slow provider calls",
    )
    parser.add_argument(
        "--protocol-attempts",
        type=int,
        default=3,
        help="maximum strict JSON regeneration attempts for malformed planner output",
    )
    parser.add_argument(
        "--approval-timeout",
        type=float,
        default=10.0,
        help="seconds before safe scoped actions auto-continue (legacy runtime)",
    )
    parser.add_argument(
        "--no-auto-continue",
        action="store_true",
        help="disable timeout auto-continuation for legacy safe actions",
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
        # Grok-style full interactive CLI (slash commands, spinner, auto-local).
        return interactive(config, args.verbose)

    original_prompt = " ".join(args.prompt)
    memory = MemoryStore()
    provider = create_provider(config)

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

    # Small local models (GGUF / tiny Ollama) cannot run the full repository coding
    # planner prompt (often 5k–20k tokens). Route conversational prompts through
    # the lightweight chat agent instead of the strict coding doer.
    provider_id = str(config.get("provider") or "").lower()
    lower_prompt = original_prompt.lower()
    coding_markers = (
        "implement",
        "refactor",
        "apply patch",
        "write a function",
        "write a class",
        "create a file",
        "edit the file",
        "pytest",
        "unit test",
        "test suite",
        "debug this",
        "repository",
        "codebase",
        "pull request",
        "git commit",
    )
    looks_like_coding = any(token in lower_prompt for token in coding_markers)
    force_chat = provider_id in {"local_gguf", "ollama"} and not looks_like_coding
    if not force_chat and len(original_prompt) < 240:
        stripped = lower_prompt.strip()
        if stripped.endswith("?") or stripped.startswith(
            ("hi", "hello", "hey", "say ", "what ", "who ", "how ", "why ", "thanks")
        ):
            force_chat = True

    if force_chat and not args.single_agent and not args.multi_agent:
        response = agent.ask(original_prompt)
        print(response.text)
        return 0 if response.text else 2

    def backend(prompt: str, system: str) -> str:
        return provider.generate(prompt, system)

    if args.single_agent or args.multi_agent:
        mode = "multi" if args.multi_agent else "single"
        policy = _execution_policy(args.approval_timeout, not args.no_auto_continue)

        def legacy_backend(prompt: str, system: str) -> str:
            return provider.generate(prompt, (system + "\n\n" + policy).strip())

        runtime = MultiAgentRuntime(
            backend=legacy_backend,
            store=store,
            max_workers=args.max_workers,
            max_attempts=args.agent_attempts,
        )
        result = runtime.run(original_prompt, mode=mode)
        if args.agent_json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(result.final_output)
        return 0 if result.final_output else 2

    progress = LiveProgressReporter(
        enabled=not args.no_progress,
        heartbeat_seconds=args.progress_heartbeat,
    )
    runtime = StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=memory,
        workspace=Path(args.workspace),
        max_steps=args.max_steps,
        protocol_attempts=args.protocol_attempts,
        progress=progress,
    )
    result = runtime.run(original_prompt)

    if args.agent_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.goal_met else 2

    if requests_strict_json(original_prompt):
        try:
            print(render_strict_json(original_prompt, result.final_output))
            return 0 if result.goal_met else 2
        except StructuredOutputError as error:
            logger.error("Strict JSON contract failed: %s", error)
            print('{"status":"failed","error":"strict_json_contract"}')
            return 2

    repository = result.execution.get("repository", {})
    files = repository.get("files", []) if isinstance(repository, dict) else []
    print(
        f"EXECUTION_MODE=repository_coding_agent\n"
        f"RUN_ID={result.run_id}\n"
        f"GOAL_MET={'true' if result.goal_met else 'false'}\n"
        f"LOOP_STEPS={len(result.steps)}\n"
        f"STOPPED_REASON={result.stopped_reason}\n"
        f"INDEXED_FILES={len(files)}\n"
        f"WORKSPACE={result.execution.get('workspace', str(Path(args.workspace).resolve()))}"
    )
    print()
    print(result.final_output)
    return 0 if result.goal_met else 2


if __name__ == "__main__":
    raise SystemExit(main())
