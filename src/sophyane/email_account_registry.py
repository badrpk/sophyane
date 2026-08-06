"""Local registry for multiple private email connector accounts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sophyane.secret_vault import get_secret

STATE_DIR = Path(
    os.environ.get(
        "SOPHYANE_STATE_DIR",
        Path.home() / ".local/state/sophyane",
    )
).expanduser()

REGISTRY_FILE = STATE_DIR / "email-accounts.json"


def _normalise_email(value: str) -> str:
    return str(value or "").strip().casefold()


def _load() -> dict[str, Any]:
    if not REGISTRY_FILE.is_file():
        return {
            "active_profile": "default",
            "accounts": {},
        }

    try:
        data = json.loads(
            REGISTRY_FILE.read_text(
                encoding="utf-8",
            )
        )
    except Exception:
        data = {}

    data.setdefault(
        "active_profile",
        "default",
    )
    data.setdefault(
        "accounts",
        {},
    )

    return data


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    REGISTRY_FILE.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        os.chmod(
            REGISTRY_FILE,
            0o600,
        )
    except OSError:
        pass


def bootstrap_default_account() -> None:
    """Register an existing default-profile mailbox without exposing secrets."""
    data = _load()

    user = get_secret(
        "default",
        "imap_user",
    )

    if not user:
        return

    address = _normalise_email(user)

    if not address:
        return

    accounts = data["accounts"]

    if address not in accounts:
        accounts[address] = {
            "email": address,
            "profile": "default",
            "label": address,
        }

    if not data.get("active_profile"):
        data["active_profile"] = "default"

    _save(data)


def register_account(
    *,
    email: str,
    profile: str,
    label: str = "",
) -> None:
    data = _load()
    address = _normalise_email(email)

    data["accounts"][address] = {
        "email": address,
        "profile": str(profile),
        "label": str(label or address),
    }

    if not data.get("active_profile"):
        data["active_profile"] = str(profile)

    _save(data)


def accounts() -> list[dict[str, str]]:
    bootstrap_default_account()
    data = _load()

    result = []

    for item in data["accounts"].values():
        result.append(
            {
                "email": str(
                    item.get("email") or ""
                ),
                "profile": str(
                    item.get("profile") or ""
                ),
                "label": str(
                    item.get("label")
                    or item.get("email")
                    or ""
                ),
            }
        )

    result.sort(
        key=lambda item: item["email"]
    )

    return result


def active_profile() -> str:
    bootstrap_default_account()
    data = _load()

    selected = str(
        data.get("active_profile")
        or "default"
    )

    return selected


def active_account() -> dict[str, str] | None:
    selected = active_profile()

    for item in accounts():
        if item["profile"] == selected:
            return item

    user = get_secret(
        selected,
        "imap_user",
    )

    if user:
        return {
            "email": _normalise_email(user),
            "profile": selected,
            "label": _normalise_email(user),
        }

    return None


def set_active_profile(
    profile: str,
) -> None:
    data = _load()
    data["active_profile"] = str(profile)
    _save(data)


def profile_for_email(
    email: str,
) -> str:
    address = _normalise_email(email)

    for item in accounts():
        if item["email"] == address:
            return item["profile"]

    # Each additional account receives its own isolated vault profile.
    return address


__all__ = [
    "REGISTRY_FILE",
    "accounts",
    "active_account",
    "active_profile",
    "bootstrap_default_account",
    "profile_for_email",
    "register_account",
    "set_active_profile",
]
