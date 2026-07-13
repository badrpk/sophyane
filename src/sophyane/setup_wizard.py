"""Interactive provider configuration wizard."""

from __future__ import annotations

from typing import Any

from sophyane.config import (
    get_secret,
    prompt_secret,
    save_config,
)
from sophyane.plugin_loader import PluginLoader


def run_setup_wizard() -> dict[str, Any]:
    loader = PluginLoader()
    providers = loader.discover()

    if not providers:
        details = "; ".join(
            f"{key}: {value}"
            for key, value in loader.errors.items()
        )
        raise RuntimeError(
            f"No provider plugins loaded. {details}"
        )

    provider_ids = sorted(providers)

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║          Sophyane Provider Setup             ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    for index, provider_id in enumerate(provider_ids, start=1):
        metadata = providers[provider_id].metadata
        suffix = (
            ""
            if metadata.requires_api_key
            else " — local, no API key"
        )

        print(
            f"  {index}. {metadata.display_name}{suffix}"
        )

    print()

    while True:
        selected = input(
            f"Select provider [1-{len(provider_ids)}]: "
        ).strip()

        try:
            provider_id = provider_ids[int(selected) - 1]
        except (ValueError, IndexError):
            print("Enter a valid provider number.")
            continue

        break

    metadata = providers[provider_id].metadata

    model = input(
        f"Model [{metadata.default_model}]: "
    ).strip() or metadata.default_model

    if metadata.requires_api_key:
        existing = get_secret(
            provider_id,
            metadata.environment_variable,
        )

        if existing:
            reuse = input(
                "An API key is already configured. Reuse it? "
                "[Y/n]: "
            ).strip().lower()

            if reuse in {"n", "no"}:
                prompt_secret(
                    provider_id,
                    metadata.environment_variable,
                )
        else:
            prompt_secret(
                provider_id,
                metadata.environment_variable,
            )

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
    print()

    return config
