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
    provider = str(config.get("provider") or "gemini")
    model = str(config.get("model") or "gemini-2.5-flash")
    return f"◆ Sophyane {__version__} | provider: {provider} | model: {model}"


def _user_start_tips() -> str:
    return (
        "First use: run `sophyane --setup` only when an API key is needed.\n"
        "Updates are detected automatically; your repositories and work files are preserved.\n"
        "Universal install/update: curl -fsSL "
        "https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash\n"
    )


def main() -> int:
    print(_runtime_identity(), file=sys.stderr, flush=True)
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli

    return run_cli()
