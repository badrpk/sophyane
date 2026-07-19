"""Interactive provider and model configuration wizard."""

from __future__ import annotations

from typing import Any

from sophyane.config import get_secret, prompt_secret, save_config
from sophyane.model_catalog import FRONTIER_MODELS, LOCAL_MODELS, ModelChoice
from sophyane.plugin_loader import PluginLoader


def _print_group(title: str, choices: list[ModelChoice], start: int) -> int:
    print(title)
    for offset, choice in enumerate(choices):
        number = start + offset
        print(f"  {number:>2}. {choice['label']}  [{choice['provider']}] — {choice['note']}")
    print()
    return start + len(choices)


def run_setup_wizard() -> dict[str, Any]:
    loader = PluginLoader()
    providers = loader.discover()
    if not providers:
        details = "; ".join(f"{key}: {value}" for key, value in loader.errors.items())
        raise RuntimeError(f"No provider plugins loaded. {details}")

    available_frontier = [item for item in FRONTIER_MODELS if item["provider"] in providers]
    available_local = [item for item in LOCAL_MODELS if item["provider"] in providers]
    choices = available_frontier + available_local

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║             Sophyane Model Setup             ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    next_number = _print_group("Top frontier models", available_frontier, 1)
    _print_group("Top local models", available_local, next_number)
    print("   0. Custom provider/model")
    print()

    while True:
        selected = input(f"Select model [1-{len(choices)}] or 0 for custom: ").strip()
        try:
            selected_number = int(selected)
        except ValueError:
            print("Enter a valid model number.")
            continue

        if selected_number == 0:
            provider_ids = sorted(providers)
            print()
            for index, provider_id in enumerate(provider_ids, start=1):
                metadata = providers[provider_id].metadata
                suffix = "" if metadata.requires_api_key else " — local, no API key"
                print(f"  {index}. {metadata.display_name}{suffix}")
            while True:
                raw_provider = input(f"Select provider [1-{len(provider_ids)}]: ").strip()
                try:
                    provider_id = provider_ids[int(raw_provider) - 1]
                    break
                except (ValueError, IndexError):
                    print("Enter a valid provider number.")
            metadata = providers[provider_id].metadata
            model = input(f"Model [{metadata.default_model}]: ").strip() or metadata.default_model
            break

        if 1 <= selected_number <= len(choices):
            choice = choices[selected_number - 1]
            provider_id = choice["provider"]
            model = choice["model"]
            metadata = providers[provider_id].metadata
            break

        print("Enter a valid model number.")

    if metadata.requires_api_key:
        existing = get_secret(provider_id, metadata.environment_variable)
        if existing:
            reuse = input("An API key is already configured. Reuse it? [Y/n]: ").strip().lower()
            if reuse in {"n", "no"}:
                prompt_secret(provider_id, metadata.environment_variable)
        else:
            prompt_secret(provider_id, metadata.environment_variable)

    config = {
        "provider": provider_id,
        "model": model,
        "timeout": 180,
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    save_config(config)

    print()
    print("Configuration saved.")
    print(f"Provider: {metadata.display_name}")
    print(f"Model:    {model}")
    if provider_id == "ollama":
        print(f"Local model command: ollama pull {model}")
    print()
    return config
