"""Sophyane configuration and private credential storage."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
from typing import Any


APP_DIR = Path.home() / ".sophyane"
CONFIG_DIR = Path.home() / ".config" / "sophyane"
CONFIG_FILE = CONFIG_DIR / "config.json"
SECRETS_FILE = CONFIG_DIR / "secrets.json"
DATA_DIR = APP_DIR / "data"
WORKSPACE_DIR = APP_DIR / "workspace"
LOG_DIR = APP_DIR / "logs"


def ensure_directories() -> None:
    for directory in (APP_DIR, CONFIG_DIR, DATA_DIR, WORKSPACE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: dict[str, Any], private: bool = False) -> None:
    ensure_directories()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
    if private:
        try:
            path.chmod(0o600)
        except OSError:
            pass


DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_FALLBACK_ORDER = (
    "gemini", "xai", "openai", "anthropic", "groq", "openrouter",
    "deepseek", "ollama", "local_gguf",
)


def default_config() -> dict[str, Any]:
    return {
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
        "timeout": 60,
        "temperature": 0.3,
        "max_tokens": 4096,
    }


def default_llm_config() -> dict[str, Any]:
    return {
        "active_provider": DEFAULT_PROVIDER,
        "fallback_order": list(DEFAULT_FALLBACK_ORDER),
        "providers": {
            "gemini": {
                "enabled": True,
                "model": DEFAULT_MODEL,
                "api_key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
            },
            "openai": {"enabled": True, "model": "gpt-4o-mini"},
            "xai": {"enabled": True, "model": "grok-3-mini"},
            "local_gguf": {"enabled": True},
        },
    }


def ensure_default_llm_files() -> None:
    ensure_directories()
    if not CONFIG_FILE.exists():
        save_json(CONFIG_FILE, default_config(), private=True)
    if not (CONFIG_DIR / "llm.json").exists():
        save_json(CONFIG_DIR / "llm.json", default_llm_config(), private=True)


def load_config() -> dict[str, Any]:
    ensure_default_llm_files()
    data = load_json(CONFIG_FILE)
    if not data:
        return default_config()
    if not str(data.get("provider") or "").strip():
        data = {**default_config(), **data}
        data["provider"] = DEFAULT_PROVIDER
        data.setdefault("model", DEFAULT_MODEL)
    return data


def save_config(config: dict[str, Any]) -> None:
    save_json(CONFIG_FILE, config)


def load_secrets() -> dict[str, Any]:
    return load_json(SECRETS_FILE)


def save_secret(provider: str, api_key: str) -> None:
    secrets = load_secrets()
    secrets[provider] = api_key
    save_json(SECRETS_FILE, secrets, private=True)


def delete_secret(provider: str) -> bool:
    """Forget every stored alias for a provider. Environment variables are untouched."""
    secrets = load_secrets()
    aliases = {provider}
    if provider == "gemini":
        aliases.update({"google", "GOOGLE_API_KEY", "GEMINI_API_KEY"})
    changed = False
    for alias in aliases:
        if alias in secrets:
            secrets.pop(alias, None)
            changed = True
    if changed:
        save_json(SECRETS_FILE, secrets, private=True)
    return changed


def get_secret(provider: str, environment_variable: str) -> str:
    environment_value = os.getenv(environment_variable, "").strip()
    if environment_value:
        return environment_value
    if provider == "gemini" or environment_variable in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}:
        for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            alt = os.getenv(env_name, "").strip()
            if alt:
                return alt
    secrets = load_secrets()
    value = str(secrets.get(provider, "")).strip()
    if value:
        return value
    if provider == "gemini":
        for alt_name in ("google", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
            alt = str(secrets.get(alt_name, "")).strip()
            if alt:
                return alt
    return ""


def prompt_secret(provider: str, environment_variable: str) -> str:
    print(f"You may alternatively set the {environment_variable} environment variable.")
    api_key = getpass.getpass("Enter API key: ").strip()
    if not api_key:
        raise ValueError("API key cannot be empty.")
    save_secret(provider, api_key)
    return api_key
