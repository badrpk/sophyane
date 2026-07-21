"""Startup provider policy and configured-provider summary."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sophyane.config import CONFIG_DIR, get_secret, load_config, save_config, save_json
from sophyane.plugin_loader import PluginLoader

LOCAL_IDS = {"local_gguf", "ollama"}
LLM_FILE = CONFIG_DIR / "llm.json"


def _load_llm() -> dict[str, Any]:
    try:
        data = json.loads(LLM_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _local_candidate(config: dict[str, Any], llm: dict[str, Any]) -> tuple[str, str] | None:
    provider = str(config.get("provider") or "").strip().lower()
    model = str(config.get("model") or "").strip()
    if provider in LOCAL_IDS:
        return provider, model
    providers = llm.get("providers") or {}
    if isinstance(providers, dict):
        for name in ("local_gguf", "ollama"):
            item = providers.get(name) or {}
            if isinstance(item, dict) and item.get("enabled") is not False and item.get("model"):
                return name, str(item["model"])
    state_path = Path.home() / ".local/state/sophyane/gguf_runtime.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    if isinstance(state, dict) and state.get("gguf_path"):
        return "local_gguf", str(state.get("model") or "local-gguf")
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


def choose_startup_provider() -> dict[str, Any]:
    config = load_config()
    llm = _load_llm()
    local = _local_candidate(config, llm)
    clouds = _configured_clouds()

    print("\nConfigured AI providers", file=sys.stderr)
    print("───────────────────────", file=sys.stderr)
    print(f"  {'✓' if local else '✗'} Local: {local[0] + ' / ' + local[1] if local else 'not configured'}", file=sys.stderr)
    if clouds:
        for provider_id, label in clouds:
            print(f"  ✓ Cloud API: {label} ({provider_id})", file=sys.stderr)
    else:
        print("  ✗ Cloud API: none configured", file=sys.stderr)

    if not sys.stdin.isatty():
        return config

    if local and clouds:
        print("\nStart this session with:", file=sys.stderr)
        print("  1. Local first — cloud only rescues repeated validator failures", file=sys.stderr)
        print(f"  2. Cloud — use {clouds[0][1]} directly", file=sys.stderr)
        print("  3. Keep current configuration", file=sys.stderr)
        while True:
            answer = input("Select [1-3, default 1]: ").strip()
            if answer in {"", "1", "2", "3"}:
                break
            print("Enter 1, 2, or 3.")

        if answer in {"", "1"}:
            local_id, local_model = local
            rescue_id = clouds[0][0]
            updated = dict(config)
            updated.update({"provider": local_id, "model": local_model, "company": "Local", "timeout": 300})
            save_config(updated)
            llm["active_provider"] = local_id
            llm["allow_quality_escalation"] = True
            llm["quality_rescue_provider"] = rescue_id
            order = [local_id, rescue_id]
            for value in llm.get("fallback_order", []) or []:
                name = str(value).strip().lower()
                if name and name not in order:
                    order.append(name)
            llm["fallback_order"] = order
            save_json(LLM_FILE, llm, private=False)
            print(f"Mode: local-first; one-shot rescue: {rescue_id}", file=sys.stderr)
            return updated

        if answer == "2":
            cloud_id, label = clouds[0]
            updated = dict(config)
            updated.update({"provider": cloud_id, "model": _cloud_model(cloud_id, config, llm), "company": label, "timeout": 180})
            save_config(updated)
            llm["active_provider"] = cloud_id
            save_json(LLM_FILE, llm, private=False)
            print(f"Mode: cloud; provider: {cloud_id}", file=sys.stderr)
            return updated

    elif local:
        print("Mode: local only; no cloud rescue API is configured.", file=sys.stderr)
    elif clouds:
        print(f"Mode: cloud ({clouds[0][0]}); no local model is configured.", file=sys.stderr)
    else:
        print("No usable provider is configured. Run `sophyane --setup`.", file=sys.stderr)
    return config
