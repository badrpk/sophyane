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
    for directory in (
        APP_DIR,
        CONFIG_DIR,
        DATA_DIR,
        WORKSPACE_DIR,
        LOG_DIR,
    ):
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


def save_json(
    path: Path,
    data: dict[str, Any],
    private: bool = False,
) -> None:
    ensure_directories()

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)

    if private:
        try:
            path.chmod(0o600)
        except OSError:
            pass


def load_config() -> dict[str, Any]:
    return load_json(CONFIG_FILE)


def save_config(config: dict[str, Any]) -> None:
    save_json(CONFIG_FILE, config)


def load_secrets() -> dict[str, Any]:
    return load_json(SECRETS_FILE)


def save_secret(provider: str, api_key: str) -> None:
    secrets = load_secrets()
    secrets[provider] = api_key
    save_json(SECRETS_FILE, secrets, private=True)


def get_secret(
    provider: str,
    environment_variable: str,
) -> str:
    environment_value = os.getenv(environment_variable, "").strip()

    if environment_value:
        return environment_value

    return str(load_secrets().get(provider, "")).strip()


def prompt_secret(provider: str, environment_variable: str) -> str:
    print(
        f"You may alternatively set the "
        f"{environment_variable} environment variable."
    )

    api_key = getpass.getpass("Enter API key: ").strip()

    if not api_key:
        raise ValueError("API key cannot be empty.")

    save_secret(provider, api_key)
    return api_key
