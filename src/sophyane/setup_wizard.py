"""Interactive company, model, credential, and local-runtime manager."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sophyane.config import (
    delete_secret,
    get_secret,
    load_config,
    prompt_secret,
    save_config,
)
from sophyane.model_catalog import CLOUD_COMPANIES, LOCAL_MODELS, CompanyChoice, ModelChoice
from sophyane.plugin_loader import PluginLoader


def _ask_number(prompt: str, minimum: int, maximum: int) -> int:
    while True:
        value = input(prompt).strip()
        try:
            number = int(value)
        except ValueError:
            print("Enter a valid number.")
            continue
        if minimum <= number <= maximum:
            return number
        print(f"Enter a number from {minimum} to {maximum}.")


def _yes(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _memory_gb() -> int:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return max(1, round(pages * page_size / (1024 ** 3)))
    except (AttributeError, OSError, ValueError):
        return 4


def _hardware() -> dict[str, Any]:
    disk = shutil.disk_usage(Path.home())
    prefix = os.getenv("PREFIX", "")
    termux = "com.termux" in prefix or Path("/data/data/com.termux").exists()
    return {
        "system": "Android/Termux" if termux else platform.system(),
        "machine": platform.machine(),
        "ram_gb": _memory_gb(),
        "free_gb": round(disk.free / (1024 ** 3), 1),
        "ollama": bool(shutil.which("ollama")),
        "nvidia": bool(shutil.which("nvidia-smi")),
        "termux": termux,
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _credential_menu(provider_id: str, metadata: Any) -> None:
    while True:
        stored = bool(get_secret(provider_id, metadata.environment_variable))
        print()
        print(f"API credential: {'configured' if stored else 'not configured'}")
        print("  1. Keep/use current API key")
        print("  2. Enter or replace API key")
        print("  3. Forget stored API key")
        print("  4. Continue")
        action = _ask_number("Select credential action [1-4]: ", 1, 4)
        if action == 1:
            if stored:
                return
            print("No API key is configured.")
        elif action == 2:
            prompt_secret(provider_id, metadata.environment_variable)
            return
        elif action == 3:
            removed = delete_secret(provider_id)
            print("Stored API key forgotten." if removed else "No stored API key was found.")
            env_value = os.getenv(metadata.environment_variable, "").strip()
            if provider_id == "gemini":
                env_value = env_value or os.getenv("GOOGLE_API_KEY", "").strip()
            if env_value:
                print("Note: an environment-variable key is still active in this shell.")
        else:
            if not stored:
                prompt_secret(provider_id, metadata.environment_variable)
            return


def _choose_cloud(providers: dict[str, Any]) -> dict[str, Any] | None:
    companies = [company for company in CLOUD_COMPANIES if company["provider"] in providers]
    print()
    print("Cloud frontier LLM companies")
    print("────────────────────────────")
    for index, company in enumerate(companies, 1):
        print(f" {index:>2}. {company['name']} — {company['note']}")
    print("  0. Back")
    selected = _ask_number(f"Select company [0-{len(companies)}]: ", 0, len(companies))
    if selected == 0:
        return None
    company: CompanyChoice = companies[selected - 1]
    print()
    print(f"{company['name']} models")
    print("─" * (len(company["name"]) + 7))
    for index, model in enumerate(company["models"], 1):
        print(f"  {index}. {model['label']} — {model['note']}")
    custom_number = len(company["models"]) + 1
    print(f"  {custom_number}. Enter custom model ID")
    print("  0. Back")
    model_number = _ask_number(f"Select model [0-{custom_number}]: ", 0, custom_number)
    if model_number == 0:
        return None
    if model_number == custom_number:
        model_id = input("Model ID: ").strip()
        if not model_id:
            print("Model ID cannot be empty.")
            return None
    else:
        model_id = company["models"][model_number - 1]["model"]
    provider_id = company["provider"]
    metadata = providers[provider_id].metadata
    _credential_menu(company["credential_provider"], metadata)
    return {
        "provider": provider_id,
        "model": model_id,
        "company": company["name"],
        "timeout": 180,
        "temperature": 0.3,
        "max_tokens": 4096,
    }


def _install_ollama(hw: dict[str, Any]) -> bool:
    if hw["ollama"]:
        return True
    print("Ollama is not installed.")
    if not _yes("Install the recommended local runtime now?"):
        return False
    if hw["termux"] and shutil.which("pkg"):
        command = ["pkg", "install", "ollama", "-y"]
    elif platform.system() == "Linux" and shutil.which("curl"):
        command = ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]
    else:
        print("Automatic installation is unavailable on this platform.")
        print("Install Ollama, then run `sophyane --setup` again.")
        return False
    print("Installing Ollama...")
    result = _run(command)
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip() or "Ollama installation failed.")
        return False
    return bool(shutil.which("ollama"))


def _installed_ollama_models() -> list[str]:
    if not shutil.which("ollama"):
        return []
    result = _run(["ollama", "list"])
    if result.returncode != 0:
        return []
    lines = result.stdout.splitlines()[1:]
    return [line.split()[0] for line in lines if line.split()]


def _manage_local_models() -> None:
    installed = _installed_ollama_models()
    if not installed:
        print("No Ollama models are installed.")
        return
    print()
    print("Installed local models")
    for index, model in enumerate(installed, 1):
        print(f"  {index}. {model}")
    print("  0. Back")
    selected = _ask_number(f"Delete model [0-{len(installed)}]: ", 0, len(installed))
    if selected == 0:
        return
    model = installed[selected - 1]
    if _yes(f"Delete local model {model} and recover disk space?"):
        result = _run(["ollama", "rm", model])
        print(result.stdout.strip() or result.stderr.strip() or "Done.")


def _choose_local(providers: dict[str, Any]) -> dict[str, Any] | None:
    if "ollama" not in providers:
        print("The Ollama provider plugin is unavailable.")
        return None
    hw = _hardware()
    print()
    print("Detected hardware")
    print("─────────────────")
    print(f" System:       {hw['system']}")
    print(f" Architecture: {hw['machine']}")
    print(f" RAM:          approximately {hw['ram_gb']} GB")
    print(f" Free storage: {hw['free_gb']} GB")
    print(f" NVIDIA GPU:   {'yes' if hw['nvidia'] else 'not detected'}")
    print(f" Ollama:       {'installed' if hw['ollama'] else 'not installed'}")

    recommended = [model for model in LOCAL_MODELS if model["min_ram_gb"] <= hw["ram_gb"]]
    if not recommended:
        recommended = list(LOCAL_MODELS[:2])
    print()
    print("Hardware-compatible local models")
    print("────────────────────────────────")
    for index, model in enumerate(recommended, 1):
        print(
            f"  {index}. {model['label']} — {model['note']} "
            f"(recommended RAM {model['min_ram_gb']}+ GB)"
        )
    custom_number = len(recommended) + 1
    print(f"  {custom_number}. Enter another Ollama model")
    print(f"  {custom_number + 1}. Delete an installed local model")
    print("  0. Back")
    selected = _ask_number(f"Select [0-{custom_number + 1}]: ", 0, custom_number + 1)
    if selected == 0:
        return None
    if selected == custom_number + 1:
        _manage_local_models()
        return None
    if selected == custom_number:
        model_id = input("Ollama model name: ").strip()
        if not model_id:
            return None
    else:
        model_id = recommended[selected - 1]["model"]

    if not _install_ollama(hw):
        return None
    installed = _installed_ollama_models()
    if model_id not in installed:
        estimated_need = next(
            (item["min_ram_gb"] for item in LOCAL_MODELS if item["model"] == model_id),
            4,
        )
        if hw["free_gb"] < max(2, estimated_need / 2):
            print("Warning: available storage may be insufficient for this model.")
        if _yes(f"Download and configure {model_id} now?", default=True):
            result = subprocess.run(["ollama", "pull", model_id], check=False)
            if result.returncode != 0:
                print("Model download failed; configuration was not changed.")
                return None
        else:
            print("Model was not downloaded; configuration was not changed.")
            return None
    return {
        "provider": "ollama",
        "model": model_id,
        "company": "Local/Ollama",
        "runtime_profile": "local",
        "timeout": 300,
        "temperature": 0.3,
        "max_tokens": 2048 if hw["ram_gb"] < 8 else 4096,
    }


def _show_current() -> None:
    config = load_config()
    print()
    print("Current Sophyane model")
    print("──────────────────────")
    print(f" Company:  {config.get('company', 'not recorded')}")
    print(f" Provider: {config.get('provider', 'not configured')}")
    print(f" Model:    {config.get('model', 'not configured')}")


def _forget_key(providers: dict[str, Any]) -> None:
    keyed = [
        (provider_id, plugin.metadata)
        for provider_id, plugin in sorted(providers.items())
        if plugin.metadata.requires_api_key
    ]
    print()
    for index, (_, metadata) in enumerate(keyed, 1):
        print(f"  {index}. {metadata.display_name}")
    print("  0. Back")
    selected = _ask_number(f"Forget provider key [0-{len(keyed)}]: ", 0, len(keyed))
    if selected == 0:
        return
    provider_id, metadata = keyed[selected - 1]
    if _yes(f"Forget the stored {metadata.display_name} API key?"):
        removed = delete_secret(provider_id)
        print("API key forgotten." if removed else "No stored key was found.")


def run_setup_wizard() -> dict[str, Any]:
    loader = PluginLoader()
    providers = loader.discover()
    if not providers:
        details = "; ".join(f"{key}: {value}" for key, value in loader.errors.items())
        raise RuntimeError(f"No provider plugins loaded. {details}")

    while True:
        print()
        print("╔══════════════════════════════════════════════╗")
        print("║          Sophyane AI Configuration           ║")
        print("╚══════════════════════════════════════════════╝")
        current = load_config()
        print(f" Current: {current.get('company', current.get('provider'))} / {current.get('model')}")
        print()
        print("  1. Select cloud LLM company and model")
        print("  2. Configure a local model for this hardware")
        print("  3. Show current configuration")
        print("  4. Switch model/company")
        print("  5. Forget a cloud API key")
        print("  6. Delete an installed local model")
        print("  0. Save and exit")
        action = _ask_number("Select action [0-6]: ", 0, 6)

        new_config: dict[str, Any] | None = None
        if action in {1, 4}:
            new_config = _choose_cloud(providers)
        elif action == 2:
            new_config = _choose_local(providers)
        elif action == 3:
            _show_current()
        elif action == 5:
            _forget_key(providers)
        elif action == 6:
            _manage_local_models()
        elif action == 0:
            return load_config()

        if new_config:
            save_config(new_config)
            print()
            print("Configuration saved and activated.")
            print(f" Provider: {new_config['provider']}")
            print(f" Model:    {new_config['model']}")
            if not _yes("Configure another provider or model?"):
                return new_config
