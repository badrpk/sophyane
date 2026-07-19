"""Interactive provider and local-model configuration wizard."""

from __future__ import annotations

from typing import Any

from sophyane.config import (
    get_secret,
    load_config,
    prompt_secret,
    save_config,
)
from sophyane.plugin_loader import PluginLoader


def _progress(message: str) -> None:
    print(f"  {message}", flush=True)


def _configure_local_gguf() -> dict[str, Any]:
    """Show every supported GGUF and install the user's selection locally."""
    from sophyane.local_runtime import (
        GGUF_DIR,
        HF_GGUF_CATALOG,
        download_hf_gguf,
        install_llama_cpp,
        list_hf_gguf_for_hardware,
        persist_gguf_state,
        persist_local_provider,
        profile_hardware,
        start_llama_server,
    )

    profile = profile_hardware()
    options = list_hf_gguf_for_hardware(profile)

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║        Sophyane Local Model Catalog          ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(
        f"Detected: {profile.cpus} CPU cores, {profile.ram_mb} MB RAM, "
        f"{profile.disk_free_mb} MB free disk, {profile.arch}, tier={profile.tier}"
    )
    print("All entries below are local GGUF models. No API key is required.")
    print("Models come from Hugging Face; llama.cpp comes from GitHub releases.")
    print()

    # list_hf_gguf_for_hardware already de-duplicates the complete supported catalog.
    for index, item in enumerate(options, start=1):
        fits = bool(item["fits_ram"] and item["fits_disk"])
        state = "RECOMMENDED" if item["recommended"] else ("FITS" if fits else "TOO LARGE")
        installed = " · installed" if item["installed"] else ""
        print(
            f"  {index}. {item['key']} — ~{item['size_mb']} MB download, "
            f"minimum {item['min_ram_mb']} MB RAM [{state}{installed}]"
        )
        print(f"     {item['notes']}")
        print(f"     https://huggingface.co/{item['repo']}")

    print()
    while True:
        selected = input(f"Select local model [1-{len(options)}]: ").strip()
        try:
            item = options[int(selected) - 1]
        except (ValueError, IndexError):
            print("Enter a valid model number.")
            continue
        break

    if not (item["fits_ram"] and item["fits_disk"]):
        print()
        print(
            "Warning: this model does not meet the detected RAM or free-disk "
            "requirement and may fail or make the device unstable."
        )
        confirm = input("Install it anyway? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            raise RuntimeError("Local model installation cancelled.")

    selected_spec = None
    for specs in HF_GGUF_CATALOG.values():
        for spec in specs:
            if spec.key == item["key"]:
                selected_spec = spec
                break
        if selected_spec is not None:
            break
    if selected_spec is None:
        raise RuntimeError(f"Unsupported local model: {item['key']}")

    print()
    print("Installing Sophyane Local. This uses no cloud API and requires no API key.")
    gguf_path = download_hf_gguf(selected_spec, progress=_progress)
    binaries = install_llama_cpp(progress=_progress)

    server_mode = True
    try:
        start_llama_server(gguf_path, progress=_progress, binaries=binaries)
    except Exception as error:  # noqa: BLE001
        server_mode = False
        if not binaries.get("cli"):
            raise
        print(f"  llama-server unavailable ({error}); using llama-cli mode.")

    persist_gguf_state(
        model_key=selected_spec.key,
        gguf_path=gguf_path,
        server=binaries.get("server", ""),
        cli=binaries.get("cli", ""),
    )
    persist_local_provider(selected_spec.key, provider="local_gguf")

    config = load_config()
    config.update(
        {
            "provider": "local_gguf",
            "model": selected_spec.key,
            "timeout": max(int(config.get("timeout", 180)), 300),
            "temperature": 0.3,
            "max_tokens": 350,
        }
    )
    save_config(config)

    print()
    print("Sophyane Local is ready.")
    print(f"Model:   {selected_spec.key}")
    print(f"GGUF:    {GGUF_DIR / selected_spec.filename}")
    print(f"Backend: {'llama-server' if server_mode else 'llama-cli'}")
    print("API key: not required")
    print()
    return config


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

    if provider_id == "local_gguf":
        return _configure_local_gguf()

    if provider_id == "ollama":
        from sophyane.local_runtime import ensure_ollama_runtime

        print()
        print("Installing an Ollama model selected for this device. No API key is required.")
        result = ensure_ollama_runtime(progress=_progress)
        if not result.ok:
            raise RuntimeError(result.message)
        return load_config()

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
