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
        "Sophyane chooses implementation defaults automatically unless you specify a language.\n"
        "Only explicit build/fix/run requests may execute tools; normal chat requests direct answers.\n"
        "Terminal demos attach to the real terminal and browser demos open any generated HTML filename.\n"
        "Generated commands stay inside the task workspace. Updates preserve repositories and user work.\n"
    )


def main() -> int:
    from sophyane.runtime_browser_patch import install_browser_patch
    from sophyane.runtime_interactive_patch import install_runtime_patch
    from sophyane.runtime_orchestration_patch import install_orchestration_patch
    from sophyane.runtime_safety import install_runtime_safety
    from sophyane.runtime_stagnation_patch import install_stagnation_patch

    install_runtime_patch()
    install_runtime_safety()
    install_browser_patch()
    install_orchestration_patch()
    install_stagnation_patch()
    print(_runtime_identity(), file=sys.stderr, flush=True)
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
