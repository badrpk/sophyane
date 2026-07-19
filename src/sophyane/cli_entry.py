"""Public CLI entry point with explicit runtime identity (Grok-style)."""
from __future__ import annotations

import sys

from sophyane.config import load_config
from sophyane.runtime_bootstrap import bootstrap_runtime, provider_readiness
from sophyane.version import __version__


def _runtime_identity(config: dict | None = None) -> str:
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    provider = str(config.get("provider") or "gemini")
    model = str(config.get("model") or "gemini-2.5-flash")
    profile = str(config.get("runtime_profile") or "auto")
    return (
        f"◆ Sophyane {__version__} | provider: {provider} | "
        f"model: {model} | device: {profile}"
    )


def _user_start_tips() -> str:
    return (
        "Start guide for users:\n"
        "  Sophyane automatically detects Termux, Android, memory and tools.\n"
        "  First cloud setup only: sophyane --setup\n"
        "  Local models: /local\n"
        "  Diagnostics: sophyane --doctor\n"
        "  Docs: https://github.com/badrpk/sophyane\n"
    )


def main() -> int:
    try:
        runtime = bootstrap_runtime()
        config = runtime["config"]
    except Exception as error:
        config = load_config()
        print(f"Sophyane startup preflight warning: {error}", file=sys.stderr)

    print(_runtime_identity(config), file=sys.stderr, flush=True)

    interactive = len(sys.argv) <= 1
    if interactive:
        ready, message = provider_readiness(config)
        if not ready:
            print(f"\nSetup required: {message}\n", file=sys.stderr, flush=True)
        print(_user_start_tips(), file=sys.stderr, flush=True)

    from sophyane.v13_cli import main as run_cli

    return run_cli()
