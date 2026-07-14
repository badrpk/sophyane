"""Sophyane v12 CLI with strict machine-output contracts."""

from __future__ import annotations

from sophyane.agent import SophyaneAgent
from sophyane.config import ensure_directories
from sophyane.logging_config import configure_logging
from sophyane.main import (
    build_parser,
    create_provider,
    handle_internal_command,
    interactive,
    list_providers,
    load_runtime_config,
    show_status,
)
from sophyane.diagnostics import run_diagnostics
from sophyane.memory import MemoryStore
from sophyane.setup_wizard import run_setup_wizard
from sophyane.structured_output import (
    StructuredOutputError,
    render_strict_json,
    requests_strict_json,
)


def main() -> int:
    ensure_directories()
    parser = build_parser()
    args = parser.parse_args()
    logger = configure_logging(args.verbose)

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
    agent = SophyaneAgent(provider, memory, logger)
    response = agent.ask(original_prompt)

    if response.text.startswith("INTERNAL_COMMAND:"):
        command = response.text.split(":", 1)[1]
        text, _ = handle_internal_command(command, config)
        print(text)
        return 0

    if requests_strict_json(original_prompt):
        try:
            print(render_strict_json(original_prompt, response.text))
            return 0
        except StructuredOutputError as error:
            logger.error("Strict JSON contract failed: %s", error)
            print(
                '{"status":"failed","error":"strict_json_contract",'
                '"message":"provider returned no valid JSON"}'
            )
            return 2

    print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
