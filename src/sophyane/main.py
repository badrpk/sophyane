#!/usr/bin/env python3
"""Sophyane command-line interface."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sophyane.agent import SophyaneAgent
from sophyane.config import (
    ensure_directories,
    get_secret,
    load_config,
)
from sophyane.diagnostics import run_diagnostics
from sophyane.logging_config import configure_logging
from sophyane.memory import MemoryStore
from sophyane.plugin_loader import PluginLoader
from sophyane.setup_wizard import run_setup_wizard
from sophyane.tools import tools_description
from sophyane.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane",
        description=(
            "Multi-provider local agentic harness with persistent "
            "memory, plugins, safe tools and repository awareness."
        ),
    )

    parser.add_argument(
        "prompt",
        nargs="*",
        help="prompt to process",
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="configure the provider and model",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="show current configuration",
    )

    parser.add_argument(
        "--providers",
        action="store_true",
        help="list discovered provider plugins",
    )

    parser.add_argument(
        "--doctor",
        action="store_true",
        help="run full self-diagnostics",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="enable verbose console logging",
    )

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def load_runtime_config() -> dict[str, Any]:
    config = load_config()
    loader = PluginLoader()
    providers = loader.discover()

    provider_id = str(
        config.get("provider", "")
    ).strip()

    if provider_id not in providers:
        return run_setup_wizard()

    metadata = providers[provider_id].metadata

    if metadata.requires_api_key:
        api_key = get_secret(
            provider_id,
            metadata.environment_variable,
        )

        if not api_key:
            return run_setup_wizard()

    return config


def create_provider(config: dict[str, Any]):
    """Create a provider with multi-backend fallback when available."""
    loader = PluginLoader()
    try:
        from sophyane.providers.fallback import build_fallback_provider

        return build_fallback_provider(loader, config)
    except Exception:
        # Hard fallback to single configured provider for bootstrap safety.
        providers = loader.discover()
        provider_id = str(config["provider"])
        provider_class = providers[provider_id]
        metadata = provider_class.metadata

        api_key = (
            get_secret(
                provider_id,
                metadata.environment_variable,
            )
            if metadata.requires_api_key
            else ""
        )

        return loader.create(
            provider_id,
            api_key=api_key,
            model=str(config["model"]),
            timeout=int(config.get("timeout", 180)),
            temperature=float(
                config.get("temperature", 0.3)
            ),
            max_tokens=int(
                config.get("max_tokens", 4096)
            ),
        )


def show_status(config: dict[str, Any]) -> str:
    loader = PluginLoader()
    providers = loader.discover()
    provider_id = str(config.get("provider", ""))
    provider_class = providers.get(provider_id)

    if provider_class:
        provider_name = (
            provider_class.metadata.display_name
        )
    else:
        provider_name = provider_id or "not configured"

    memory = MemoryStore()
    fallback_chain = "n/a"
    try:
        from sophyane.providers.fallback import (
            build_fallback_provider,
            resolve_provider_order,
        )

        order = resolve_provider_order(provider_id)
        fallback_chain = " -> ".join(order)
        # Probe which keys actually instantiate without generating.
        chain_provider = build_fallback_provider(loader, config)
        fallback_chain = " -> ".join(chain_provider.chain) + " (ready)"
    except Exception as error:  # noqa: BLE001
        fallback_chain = f"unavailable ({error})"

    return "\n".join(
        [
            f"Sophyane {__version__}",
            f"Provider: {provider_name}",
            f"Model: {config.get('model', 'not configured')}",
            f"Fallback chain: {fallback_chain}",
            f"Timeout: {config.get('timeout', 180)} seconds",
            f"Memories: {memory.count()}",
            f"Plugins: {len(providers)}",
            (
                "Plugin errors: "
                + (
                    ", ".join(
                        f"{key}: {value}"
                        for key, value
                        in loader.errors.items()
                    )
                    or "none"
                )
            ),
        ]
    )


def list_providers() -> str:
    loader = PluginLoader()
    providers = loader.discover()

    lines = ["Discovered provider plugins:"]

    for provider_id in sorted(providers):
        metadata = providers[provider_id].metadata
        lines.append(
            f"- {provider_id}: {metadata.display_name} "
            f"(default model: {metadata.default_model})"
        )

    if loader.errors:
        lines.append("Plugin load errors:")

        for plugin, error in loader.errors.items():
            lines.append(f"- {plugin}: {error}")

    return "\n".join(lines)


def handle_internal_command(
    command: str,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if command == "status":
        return show_status(config), config

    if command == "providers":
        return list_providers(), config

    if command == "doctor":
        _, report = run_diagnostics()
        return report, config

    if command == "setup":
        updated = run_setup_wizard()
        return "Provider configuration updated.", updated

    return f"Unknown internal command: {command}", config


def interactive(config: dict[str, Any], verbose: bool) -> int:
    """Launch the Grok-style interactive CLI."""
    from sophyane.tui import run_grok_style_tui

    return run_grok_style_tui(config=config, verbose=verbose)


def main() -> int:
    ensure_directories()
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    if args.doctor:
        passed, report = run_diagnostics()
        print(report)
        return 0 if passed else 1

    if args.providers:
        print(list_providers())
        return 0

    if args.setup:
        config = run_setup_wizard()
    else:
        config = load_runtime_config()

    if args.status:
        print(show_status(config))
        return 0

    if args.prompt:
        logger = configure_logging(args.verbose)
        memory = MemoryStore()
        provider = create_provider(config)
        agent = SophyaneAgent(
            provider,
            memory,
            logger,
        )

        response = agent.ask(" ".join(args.prompt))

        if response.text.startswith("INTERNAL_COMMAND:"):
            command = response.text.split(":", 1)[1]
            text, _ = handle_internal_command(
                command,
                config,
            )
            print(text)
        else:
            print(response.text)

        return 0

    return interactive(config, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
