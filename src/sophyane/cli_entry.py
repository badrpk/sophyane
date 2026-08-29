"""Public CLI entry point with explicit runtime identity."""
from __future__ import annotations
import os

import sys

from sophyane.config import load_config
from sophyane.version import __version__

# SOPHYANE_TRANSIENT_SESSION_BANNER_V1
def _session_ready_model(
    configured_model: str | None,
) -> str:
    """Resolve the model label owned by the current session mode.

    SOPHYANE_SESSION_MODEL is transient process state. It is authoritative
    only when the current process explicitly selected a model-bearing
    transient mode. Otherwise persisted/current config owns the banner.
    """

    configured = str(
        configured_model
        or ""
    ).strip()

    session_mode = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODE"
        )
        or ""
    ).strip()

    if session_mode not in {
        "local_llm",
        "cloud_llm",
        "nifdu_llm",
    }:
        return configured

    return str(
        os.environ.get(
            "SOPHYANE_SESSION_MODEL"
        )
        or configured
    ).strip()




def _runtime_identity() -> str:
    try:
        config = load_config()
    except Exception:
        config = {}

    model = str(_session_ready_model(config.get("model")) or "not configured")

    try:
        from sophyane.connectors.runtime import list_connectors

        email_ready = any(
            connector.connector_id.startswith("email")
            and connector.available
            for connector in list_connectors()
        )
    except Exception:
        email_ready = False

    status = [model]

    if email_ready:
        status.append("Email connected")

    status.append("Ready")
    if os.environ.get("SOPHYANE_SLI_ONLY") == "1" or os.environ.get("SOPHYANE_SESSION_MODE") == "sli_chunks":
        status = [("SLI Graph" if os.environ.get("SOPHYANE_SLI_GRAPH") == "1" else "SLI chunks"), "Ready"]

    if os.environ.get("SOPHYANE_SLI_CONTINUOUS") == "1":
        status = ["Continuous SLI learning", "Ready"]

    return (
        f"◆ Sophyane {__version__}\n"
        + (
            "Continuous SLI learning · Ready"
            if os.environ.get("SOPHYANE_SLI_CONTINUOUS") == "1"
            else (
                "Cascade · Ready" if __import__("os").environ.get("SOPHYANE_SESSION_MODE")=="cascade" else (("SLI Graph · Ready" if os.environ.get("SOPHYANE_SLI_GRAPH") == "1" else "SLI chunks · Ready") if __import__("os").environ.get("SOPHYANE_SLI_ONLY")=="1" else ("SLI Graph · Ready" if os.environ.get("SOPHYANE_SLI_GRAPH") == "1" else "SLI chunks · Ready"))
                if (
                    os.environ.get("SOPHYANE_SLI_ONLY") == "1"
                    or os.environ.get("SOPHYANE_SESSION_MODE") == "sli_chunks"
                )
                else " · ".join(status)
            )
        )
    )


def _user_start_tips() -> str:
    """Normal startup intentionally remains uncluttered."""
    return ""


def _metadata_only_invocation() -> bool:
    return any(arg in {"-V", "--version", "--status", "--providers", "--doctor"} for arg in sys.argv[1:])


def _start_local_server_if_needed() -> None:
    # SLI-only modes do not use an LLM. Never inspect, start, or report the
    # llama.cpp/GGUF runtime for these sessions, even when local_gguf is saved
    # as the default provider in the persistent configuration.
    if (
        _metadata_only_invocation()
        or os.environ.get("SOPHYANE_SLI_ONLY") == "1"
        or os.environ.get("SOPHYANE_SLI_GRAPH") == "1"
        or os.environ.get("SOPHYANE_SLI_CONTINUOUS") == "1"
        or os.environ.get("SOPHYANE_SESSION_MODE") in {
            "sli_chunks",
            "sli_graph",
            "continuous_sli",
        }
    ):
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



# SOPHYANE_CANONICAL_WORKSPACE_V1
def _canonicalize_launch_workspace() -> str | None:
    """Move unsafe/default launch directories to the canonical Sophyane repo.

    Explicit project directories are preserved.  This specifically prevents
    WSL sessions or native Windows shells launched from Windows System32
    from becoming the execution workspace for coding/build tasks.
    """
    import os
    from pathlib import Path

    cwd = Path.cwd()

    normalized = str(cwd).replace("\\", "/").lower().rstrip("/")

    unsafe_launch = (
        normalized.endswith("/windows/system32")
        or normalized.endswith("/windows")
        or normalized.endswith("windows/system32")
        or normalized in {
            "/mnt/c",
            "/mnt/c/windows",
            "/mnt/c/windows/system32",
            "c:/windows",
            "c:/windows/system32",
            "c:",
        }
    )

    if not unsafe_launch:
        return None

    home_dir = Path.home()
    if os.environ.get("HOME") and not (home_dir / "sophyane-repo").exists():
        env_home = Path(os.environ["HOME"])
        if env_home.exists():
            home_dir = env_home

    candidates = (
        home_dir / "sophyane-repo",
        home_dir / "sophyane",
    )

    for candidate in candidates:
        if (
            candidate.is_dir()
            and (
                candidate / "pyproject.toml"
            ).is_file()
        ):
            os.chdir(candidate)
            return str(candidate)

    return None


def main() -> int:

    # SOPHYANE_STARTUP_AUTO_UPDATE_V1
    # Update before runtime/provider initialization so a
    # successfully updated installation is re-executed before
    # any normal Sophyane services are started.
    try:
        from sophyane.startup_update import (
            maybe_update_before_startup,
        )

        maybe_update_before_startup()

    except KeyboardInterrupt:
        raise

    except Exception as error:
        # Update availability must never become startup
        # availability. Sophyane remains usable offline.
        print(
            f"◆ Sophyane update warning: {error}",
            file=sys.stderr,
            flush=True,
        )

    # SOPHYANE_CANONICAL_WORKSPACE_CALL_V1
    _canonicalize_launch_workspace()
    from sophyane.runtime_artifact_patch import install_artifact_patch
    from sophyane.runtime_browser_patch import install_browser_patch
    from sophyane.runtime_deep_agent_patch import install_deep_agent_runtime
    from sophyane.runtime_input_patch import install_input_patch
    from sophyane.runtime_interactive_patch import install_runtime_patch
    from sophyane.runtime_interrupt_patch import install_interrupt_patch
    from sophyane.runtime_intent_refinement_patch import install_intent_refinement
    from sophyane.runtime_orchestration_patch import install_orchestration_patch
    from sophyane.runtime_premium_asset_pipeline import install_premium_asset_pipeline
    from sophyane.runtime_provider_context_patch import install_provider_context_patch
    from sophyane.runtime_capability_acquisition_patch import install_capability_acquisition_patch
    from sophyane.runtime_provider_error_patch import install_provider_error_patch
    from sophyane.runtime_quality_escalation import install_quality_escalation
    from sophyane.runtime_safety import install_runtime_safety
    # SOPHYANE_FILESYSTEM_CAPABILITIES_V20
    from sophyane.runtime_filesystem_capabilities_v20 import install_filesystem_capabilities_v20
    from sophyane.runtime_software_routing_guard import install_software_routing_guard
    from sophyane.runtime_snake_semantic_repair import install_snake_semantic_repair
    from sophyane.runtime_stagnation_patch import install_stagnation_patch

    install_quality_escalation()
    install_runtime_patch()
    install_runtime_safety()
    install_browser_patch()
    install_orchestration_patch()
    install_stagnation_patch()
    install_artifact_patch()
    install_deep_agent_runtime()
    from sophyane.runtime_cursor_tab_patch import install_cursor_tab_patch
    install_cursor_tab_patch()
    install_provider_context_patch()
    install_interrupt_patch()
    install_provider_error_patch()
    install_input_patch()
    install_intent_refinement()
    # SOPHYANE_FILESYSTEM_CAPABILITIES_V20
    install_filesystem_capabilities_v20()
    install_premium_asset_pipeline()
    # Keep mission routing outermost after all provider wrappers.
    install_capability_acquisition_patch()
    # Executable software projects must bypass editable visual-session routing.
    install_software_routing_guard()
    # Semantic browser-game repair must see the final wrapped validator and
    # continuation prompt, so it is installed after all other runtime patches.
    install_snake_semantic_repair()

    try:
        from sophyane.platform_kernel import ensure_platform_filesystem

        ensure_platform_filesystem()
    except Exception as error:  # noqa: BLE001
        print(f"◆ Platform filesystem warning: {error}", file=sys.stderr, flush=True)

    if len(sys.argv) <= 1:
        try:
            from sophyane.startup_policy import choose_startup_provider

            choose_startup_provider()
        except (EOFError, KeyboardInterrupt):
            print("\nStartup selection cancelled; keeping current configuration.", file=sys.stderr)
        except Exception as error:
            print(f"◆ Startup provider selection warning: {error}", file=sys.stderr)

    # SOPHYANE_MODE2_RUNTIME_ISOLATION_V1
    #
    # SLI execution/runtime wrappers are not global Sophyane authority.
    # They exist only inside an explicitly selected Mode-2 session.
    if (
        os.environ.get("SOPHYANE_SESSION_MODE")
        == "sli_graph"
    ):
        from sophyane.runtime_sli_brain import install_sli_brain
        from sophyane.runtime_sli_builder import install_sli_builder
        from sophyane.runtime_sli_capability_planner import (
            install_sli_capability_planner,
        )
        from sophyane.runtime_sli_intent_patch import (
            install_sli_intent_routing,
        )
        from sophyane.runtime_sli_mission_os import install_sli_mission_os
        from sophyane.runtime_sli_onset_feedback import (
            install_sli_onset_feedback,
        )

        install_sli_intent_routing()
        install_sli_onset_feedback()
        install_sli_capability_planner()
        install_sli_builder()
        install_sli_mission_os()
        install_sli_brain()

    # SOPHYANE_FRESH_PREVIEW_INSTALL_V1
    # All explicit SLI previews use the exact-workspace, no-store server.
    if (
        os.environ.get("SOPHYANE_SESSION_MODE")
        == "sli_graph"
    ):
        try:
            import sophyane.sli_capability_engine as _sli_engine

            from sophyane.code_memory.fresh_preview import (
                preview_workspace as _fresh_preview_workspace,
            )

            _sli_engine.preview_sli_artifact = (
                _fresh_preview_workspace
            )

        except Exception as error:
            print(
                f"◆ Fresh preview installation warning: {error}",
                file=sys.stderr,
                flush=True,
            )

    print(_runtime_identity(), file=sys.stderr, flush=True)
    _start_local_server_if_needed()
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    # SOPHYANE_CONTINUOUS_SLI_CLI_V1
    if os.environ.get("SOPHYANE_SLI_CONTINUOUS") == "1":
        from sophyane.code_memory.continuous_sli_loop import (
            run_continuous_sli_loop,
        )

        return run_continuous_sli_loop()

    from sophyane.v13_cli import main as run_cli
    try:
        return run_cli()
    finally:
        from sophyane.runtime_cancel import cancel_all
        cancel_all()


if __name__ == "__main__":
    raise SystemExit(main())
# SOPHYANE_FLYWHEEL_BANNER
