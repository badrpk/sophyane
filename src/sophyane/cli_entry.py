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
    return f"◆ Sophyane {__version__} | provider: {provider} | model: {model}"


def _user_start_tips() -> str:
    return (
        "Sophyane checks provider credentials before starting. Use `sophyane --setup` to switch company/model, replace or forget API keys, or configure local models.\n"
        "Coding tasks use a bounded build → verify → repair loop and ask for a language/framework when the request does not specify one.\n"
        "Updates preserve repositories and user work.\n"
    )


def main() -> int:
    from sophyane.task_runtime import install_agent_hooks

    install_agent_hooks()
    print(_runtime_identity(), file=sys.stderr, flush=True)
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
