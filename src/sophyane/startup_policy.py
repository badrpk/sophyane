"""Startup provider policy and configured-provider summary."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from sophyane.config import CONFIG_DIR, get_secret, load_config, save_config, save_json
from sophyane.plugin_loader import PluginLoader

LOCAL_IDS = {"local_gguf"}
LLM_FILE = CONFIG_DIR / "llm.json"


def _load_llm() -> dict[str, Any]:
    try:
        data = json.loads(LLM_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _local_candidate(config: dict[str, Any], llm: dict[str, Any]) -> tuple[str, str] | None:
    # SOPHYANE_LOCAL_RUNTIME_AUTHORITY_V1
    #
    # The validated GGUF runtime is authoritative for local-model identity.
    # Provider/config metadata may lag behind after provisioning or model
    # replacement and must not silently relabel the actual llama.cpp worker.
    state_path = (
        Path.home()
        / ".local/state/sophyane/gguf_runtime.json"
    )

    try:
        state = json.loads(
            state_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        state = {}

    if isinstance(state, dict):
        gguf_path = str(
            state.get("gguf_path")
            or ""
        ).strip()

        runtime_model = str(
            state.get("model")
            or ""
        ).strip()

        if gguf_path:
            path = Path(
                gguf_path
            ).expanduser()

            if path.is_file():
                if not runtime_model:
                    runtime_model = path.stem

                return (
                    "local_gguf",
                    runtime_model,
                )

    # No validated runtime exists. Fall back to saved provider metadata.
    provider = str(
        config.get("provider")
        or ""
    ).strip().lower()

    model = str(
        config.get("model")
        or ""
    ).strip()

    if (
        provider in LOCAL_IDS
        and model
    ):
        return (
            provider,
            model,
        )

    providers = (
        llm.get("providers")
        or {}
    )

    if isinstance(
        providers,
        dict,
    ):
        for name in (
            "local_gguf",
        ):
            item = (
                providers.get(name)
                or {}
            )

            if (
                isinstance(item, dict)
                and item.get("enabled") is not False
                and item.get("model")
            ):
                return (
                    name,
                    str(item["model"]),
                )

    return None


def _configured_clouds() -> list[tuple[str, str]]:
    loader = PluginLoader()
    result: list[tuple[str, str]] = []
    for provider_id, plugin in sorted(loader.discover().items()):
        if provider_id in LOCAL_IDS or not plugin.metadata.requires_api_key:
            continue
        key = get_secret(provider_id, plugin.metadata.environment_variable)
        if provider_id == "gemini":
            key = key or get_secret("gemini", "GOOGLE_API_KEY")
        if key:
            result.append((provider_id, plugin.metadata.display_name))
    return result


def _cloud_model(provider_id: str, config: dict[str, Any], llm: dict[str, Any]) -> str:
    if str(config.get("provider") or "").lower() == provider_id and config.get("model"):
        return str(config["model"])
    providers = llm.get("providers") or {}
    item = providers.get(provider_id) if isinstance(providers, dict) else None
    if isinstance(item, dict) and item.get("model"):
        return str(item["model"])
    plugin = PluginLoader().discover().get(provider_id)
    return str(plugin.metadata.default_model) if plugin else ""


def _verbose_startup_enabled() -> bool:
    return str(
        os.environ.get("SOPHYANE_VERBOSE_STARTUP")
        or os.environ.get("SOPHYANE_VERBOSE")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}


def _install_topic_learning_mode() -> None:
    """Patch the existing continuous entry point after startup selection."""
    from sophyane.code_memory import continuous_sli_loop
    from sophyane.code_memory.topic_learning import run_topic_learning_loop

    continuous_sli_loop.run_continuous_sli_loop = run_topic_learning_loop


def choose_startup_provider() -> dict[str, Any]:
    config = load_config()
    llm = _load_llm()
    local = _local_candidate(config, llm)
    clouds = _configured_clouds()

    verbose_startup = _verbose_startup_enabled()

    if verbose_startup:
        print("\nConfigured AI providers", file=sys.stderr)
        print("───────────────────────", file=sys.stderr)
        local_label = local[0] + " / " + local[1] if local else "not configured"
        print(f"  {'✓' if local else '✗'} Local: {local_label}", file=sys.stderr)
        if clouds:
            for provider_id, label in clouds:
                print(f"  ✓ Cloud API: {label} ({provider_id})", file=sys.stderr)
        else:
            print("  ✗ Cloud API: none configured", file=sys.stderr)

    # SOPHYANE_NONINTERACTIVE_SESSION_MODE_V1
    #
    # Interactive sessions retain the startup menu. Automation may select
    # the same session semantics explicitly without pretending stdin is a TTY.
    requested_mode = str(
        os.environ.get("SOPHYANE_SESSION_MODE")
        or ""
    ).strip().lower()

    if not sys.stdin.isatty():
        if requested_mode in {"sli_graph", "sli_chunks"}:
            os.environ["SOPHYANE_SESSION_MODE"] = "sli_graph"
            os.environ["SOPHYANE_SLI_GRAPH"] = "1"
            os.environ["SOPHYANE_SLI_ONLY"] = "1"

            updated = dict(config)
            updated.update({
                "company": "SLI",
                "timeout": 60,
            })

            return updated

        if requested_mode == "learning":
            # SOPHYANE_NONINTERACTIVE_MODE5_LEARNING_V1
            os.environ["SOPHYANE_SESSION_MODE"] = "learning"
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ["SOPHYANE_SLI_CONTINUOUS"] = "1"
            os.environ["SOPHYANE_TOPIC_LEARNING"] = "1"
            _install_topic_learning_mode()

            updated = dict(config)
            updated.update({
                "company": "Sophyane Learning",
                "timeout": 300,
            })

            return updated

        if requested_mode == "local_llm":
            if not local:
                return config

            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)
            os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)
            os.environ["SOPHYANE_LOCAL_ONLY"] = "1"
            os.environ["SOPHYANE_DISABLE_CLOUD_FALLBACK"] = "1"

            local_id, local_model = local

            updated = dict(config)
            updated.update({
                "provider": local_id,
                "model": local_model,
                "company": "Local",
                "timeout": 300,
            })

            llm["active_provider"] = local_id
            llm["fallback_order"] = [local_id]
            llm["allow_quality_escalation"] = False
            llm["quality_rescue_provider"] = ""
            llm["allow_local_fallbacks"] = False
            llm["allow_cloud_local_rescue"] = False

            return updated

        if requested_mode == "cloud_llm":
            if not clouds:
                return config

            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)
            os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)
            os.environ.pop("SOPHYANE_LOCAL_ONLY", None)
            os.environ.pop("SOPHYANE_DISABLE_CLOUD_FALLBACK", None)

            cloud_id, label = clouds[0]

            updated = dict(config)
            updated.update({
                "provider": cloud_id,
                "model": _cloud_model(
                    cloud_id,
                    config,
                    llm,
                ),
                "company": label,
                "timeout": 180,
            })

            llm["active_provider"] = cloud_id

            return updated

        # SOPHYANE_NONINTERACTIVE_DEFAULT_RACE_V1
        #
        # No explicit automated mode means cooperative execution.
        # Do not silently inherit a stale saved provider as execution policy.
        os.environ["SOPHYANE_SESSION_MODE"] = "race"

        return config

    if local or clouds:
        # SOPHYANE_FIVE_MODE_STARTUP_MENU_V1
        #
        # Session-mode visibility is independent from provider
        # availability. Keep all five Sophyane operating modes
        # visible and mark provider-specific modes unavailable.
        print(
            "\nStart this session with:",
            file=sys.stderr,
        )

        print(
            "  1. Sophyane — intelligently decide between available capabilities",
            file=sys.stderr,
        )

        print(
            "  2. SLI Graph — memory + internet, no LLM",
            file=sys.stderr,
        )

        if local:
            print(
                "  3. Local LLM — llama.cpp / GGUF on-device model",
                file=sys.stderr,
            )
        else:
            print(
                "  3. Local LLM — unavailable; no local model configured",
                file=sys.stderr,
            )

        if clouds:
            print(
                f"  4. Cloud LLM — use {clouds[0][1]}",
                file=sys.stderr,
            )
        else:
            print(
                "  4. Cloud LLM — unavailable; no cloud API configured",
                file=sys.stderr,
            )

        print(
            "  5. Sophyane Learning — acquire + embed until saturation/Ctrl+C",
            file=sys.stderr,
        )

        while True:
            answer = input(
                "Select [1-5, default 1]: "
            ).strip()

            if answer in {"", "1", "2", "5"}:
                break

            if answer == "3":
                if local:
                    break

                print(
                    "Local LLM unavailable. "
                    "Configure a local model first."
                )
                continue

            if answer == "4":
                if clouds:
                    break

                print(
                    "Cloud LLM unavailable. "
                    "Configure a cloud provider with "
                    "`sophyane --setup`."
                )
                continue

            print("Enter 1, 2, 3, 4, or 5.")

        if answer in {"", "1"}:
            # Sophyane owns execution policy in automatic mode.
            # No provider/capability is forced at startup.
            os.environ["SOPHYANE_SESSION_MODE"] = "race"

            # Remove strict-mode flags that could otherwise constrain
            # Sophyane's adaptive decision/race.
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ.pop("SOPHYANE_LOCAL_ONLY", None)
            os.environ.pop("SOPHYANE_DISABLE_CLOUD_FALLBACK", None)
            os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)
            os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)

            print(
                "Mode: Sophyane Auto — adaptive capability selection + race",
                file=sys.stderr,
            )
            return config

        if answer == "2":
            os.environ["SOPHYANE_SESSION_MODE"] = "sli_graph"
            os.environ["SOPHYANE_SLI_GRAPH"] = "1"
            os.environ["SOPHYANE_SLI_ONLY"] = "1"
            # SOPHYANE_MODE2_TRANSIENT_CONFIG_V1
            #
            # Mode-2 execution policy is session-local. Never persist
            # SLI company/timeout metadata into the provider configuration,
            # otherwise a later Local/Cloud session inherits Mode-2 state.
            os.environ.pop("SOPHYANE_LOCAL_ONLY", None)
            os.environ.pop("SOPHYANE_DISABLE_CLOUD_FALLBACK", None)
            os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)
            os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)

            updated = dict(config)
            updated.update({"company": "SLI", "timeout": 60})

            print(
                "Mode: SLI Graph + internet (no local/cloud LLM)",
                file=sys.stderr,
            )
            return updated

        if answer == "5":
            # SOPHYANE_MODE5_DEDICATED_LEARNING_AUTHORITY_V1
            #
            # Learning is intentionally independent from Mode-2 SLI Graph.
            # It may acquire/embed training material through its dedicated
            # learning loop, but must not acquire SLI execution authority.
            os.environ["SOPHYANE_SESSION_MODE"] = "learning"
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ["SOPHYANE_SLI_CONTINUOUS"] = "1"
            os.environ["SOPHYANE_TOPIC_LEARNING"] = "1"
            _install_topic_learning_mode()

            # SOPHYANE_MODE5_TRANSIENT_CONFIG_V1
            #
            # Learning mode is session policy, not provider configuration.
            os.environ.pop("SOPHYANE_LOCAL_ONLY", None)
            os.environ.pop("SOPHYANE_DISABLE_CLOUD_FALLBACK", None)

            updated = dict(config)
            updated.update({
                "company": "Sophyane Learning",
                "timeout": 300,
            })
            print(
                "Mode: Sophyane Learning "
                "(acquire + embed until saturation/Ctrl+C)",
                file=sys.stderr,
            )
            return updated

        if answer == "3":
            # Option 3 is intentionally strict local-only mode.
            # Never consult, rescue through, or fall back to a cloud model.
            os.environ["SOPHYANE_SESSION_MODE"] = "local_llm"
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)
            os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)
            os.environ["SOPHYANE_LOCAL_ONLY"] = "1"
            os.environ["SOPHYANE_DISABLE_CLOUD_FALLBACK"] = "1"

            local_id, local_model = local

            updated = dict(config)
            updated.update({
                "provider": local_id,
                "model": local_model,
                "company": "Local",
                "timeout": 300,
            })

            # SOPHYANE_TRANSIENT_SESSION_PROVIDER_V1
            # Explicit startup provider selection is session-scoped.
            os.environ["SOPHYANE_SESSION_PROVIDER"] = local_id
            os.environ["SOPHYANE_SESSION_MODEL"] = local_model
            os.environ["SOPHYANE_SESSION_TIMEOUT"] = "300"

            llm["active_provider"] = local_id
            llm["fallback_order"] = [local_id]
            llm["allow_quality_escalation"] = False
            llm["quality_rescue_provider"] = ""
            llm["allow_local_fallbacks"] = False
            llm["allow_cloud_local_rescue"] = False

            providers = llm.setdefault("providers", {})
            if isinstance(providers, dict):
                local_entry = providers.setdefault(local_id, {})
                if isinstance(local_entry, dict):
                    local_entry["enabled"] = True

            save_json(LLM_FILE, llm, private=False)

            print(
                f"Mode: Local LLM only ({local_model}); "
                "cloud fallback disabled",
                file=sys.stderr,
            )
            return updated

        if answer == "4":
            os.environ["SOPHYANE_SESSION_MODE"] = "cloud_llm"
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
            os.environ.pop("SOPHYANE_SLI_ONLY", None)
            os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)
            os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)
            os.environ.pop("SOPHYANE_LOCAL_ONLY", None)
            os.environ.pop("SOPHYANE_DISABLE_CLOUD_FALLBACK", None)

            cloud_id, label = clouds[0]
            cloud_model = _cloud_model(
                cloud_id,
                config,
                llm,
            )

            updated = dict(config)
            updated.update({
                "provider": cloud_id,
                "model": cloud_model,
                "company": label,
                "timeout": 180,
            })

            # SOPHYANE_TRANSIENT_SESSION_PROVIDER_V1
            # Explicit startup provider selection is session-scoped.
            os.environ["SOPHYANE_SESSION_PROVIDER"] = cloud_id
            os.environ["SOPHYANE_SESSION_MODEL"] = cloud_model
            os.environ["SOPHYANE_SESSION_TIMEOUT"] = "180"

            llm["active_provider"] = cloud_id
            save_json(LLM_FILE, llm, private=False)
            print(f"Mode: Cloud LLM ({cloud_id})", file=sys.stderr)
            return updated

    elif clouds:
        if verbose_startup:
            print(f"Mode: cloud ({clouds[0][0]}); no local model is configured.", file=sys.stderr)
    else:
        print("No usable provider is configured. Run `sophyane --setup`.", file=sys.stderr)
    return config
