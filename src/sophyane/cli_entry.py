"""Public CLI entry point with explicit runtime identity."""
from __future__ import annotations

import sys

from sophyane.config import load_config
from sophyane.version import __version__


def _runtime_identity() -> str:
    try:
        config = load_config()
    except Exception:
        config = {}
    provider = str(config.get("provider") or "not configured")
    model = str(config.get("model") or "not configured")
    return f"🧠 Sophyane {__version__} | LLM provider: {provider} | model: {model}"


def main() -> int:
    # stderr keeps --agent-json stdout valid while making the LLM visible first.
    print(_runtime_identity(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli

    return run_cli()
