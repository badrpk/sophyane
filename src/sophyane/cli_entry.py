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
        "Use `/setup` to change models or credentials, `/status` to inspect the active chain, "
        "`/new` for a fresh project, and `/quit` to exit.\n"
        "Only explicit build/fix/run requests execute tools; normal chat requests answer directly.\n"
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
    except Exception as error:
        print(f"◆ Local inference startup warning: {error}", file=sys.stderr, flush=True)


def main() -> int:
    from sophyane.runtime_artifact_patch import install_artifact_patch
    from sophyane.runtime_browser_patch import install_browser_patch
    from sophyane.runtime_input_patch import install_input_patch
    from sophyane.runtime_interactive_patch import install_runtime_patch
    from sophyane.runtime_interrupt_patch import install_interrupt_patch
    from sophyane.runtime_orchestration_patch import install_orchestration_patch
    from sophyane.runtime_provider_error_patch import install_provider_error_patch
    from sophyane.runtime_quality_escalation import install_quality_escalation
    from sophyane.runtime_safety import install_runtime_safety
    from sophyane.runtime_stagnation_patch import install_stagnation_patch

    install_quality_escalation()
    install_runtime_patch()
    install_runtime_safety()
    install_browser_patch()
    install_orchestration_patch()
    install_stagnation_patch()
    # Install last so every active execution-loop implementation receives the
    # same provider-neutral raw/JSON/markdown artifact normalization.
    install_artifact_patch()
    install_interrupt_patch()
    install_provider_error_patch()
    install_input_patch()

    # Interactive startup explicitly reports configured APIs and asks whether the
    # user wants local-first execution or direct cloud execution. Metadata and
    # setup commands remain non-interactive and predictable.
    if len(sys.argv) <= 1:
        try:
            from sophyane.startup_policy import choose_startup_provider

            choose_startup_provider()
        except (EOFError, KeyboardInterrupt):
            print("\nStartup selection cancelled; keeping current configuration.", file=sys.stderr)
        except Exception as error:
            print(f"◆ Startup provider selection warning: {error}", file=sys.stderr)

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
