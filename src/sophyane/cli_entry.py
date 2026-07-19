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


def _metadata_only_invocation() -> bool:
    return any(arg in {"-V", "--version", "--status", "--providers", "--doctor"} for arg in sys.argv[1:])


def _start_local_server_if_needed() -> None:
    if _metadata_only_invocation():
        return
    try:
        config = load_config()
        if str(config.get("provider") or "").strip().lower() != "local_gguf":
            return
        from sophyane.local_server import ensure_server_background

        ok, message = ensure_server_background()
        prefix = "◆ Local inference:" if ok else "◆ Local inference unavailable:"
        print(f"{prefix} {message}", file=sys.stderr, flush=True)
    except Exception as error:  # startup must remain usable
        print(f"◆ Local inference startup warning: {error}", file=sys.stderr, flush=True)


def main() -> int:
    from sophyane.runtime_browser_patch import install_browser_patch
    from sophyane.runtime_interactive_patch import install_runtime_patch
    from sophyane.runtime_interrupt_patch import install_interrupt_patch
    from sophyane.runtime_orchestration_patch import install_orchestration_patch
    from sophyane.runtime_provider_error_patch import install_provider_error_patch
    from sophyane.runtime_safety import install_runtime_safety
    from sophyane.runtime_stagnation_patch import install_stagnation_patch

    install_runtime_patch()
    install_runtime_safety()
    install_browser_patch()
    install_orchestration_patch()
    install_stagnation_patch()
    install_interrupt_patch()
    install_provider_error_patch()
    print(_runtime_identity(), file=sys.stderr, flush=True)
    _start_local_server_if_needed()
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli
    try:
        return run_cli()
    finally:
        from sophyane.runtime_cancel import cancel_all
        cancel_all()


if __name__ == "__main__":
    raise SystemExit(main())