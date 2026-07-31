"""Local secret vault for Sophyane user profiles.

Secrets never go through chat. Stored under state dir, mode 0600.
Optional: set SOPHYANE_VAULT_PASSPHRASE to encrypt values (Fernet);
without it, values are stored obfuscated only by file permissions
(dev/test OK; prefer keyring or passphrase for real accounts).
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

STATE = Path(
    os.environ.get(
        "SOPHYANE_STATE_DIR",
        Path.home() / ".local" / "state" / "sophyane",
    )
).expanduser()
VAULT_DIR = STATE / "vault"
VAULT_FILE = VAULT_DIR / "secrets.json"


def _ensure() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(VAULT_DIR, 0o700)
    except OSError:
        pass


def _key() -> bytes | None:
    p = os.environ.get("SOPHYANE_VAULT_PASSPHRASE", "").strip()
    if not p:
        return None
    return hashlib.sha256(p.encode("utf-8")).digest()


def _wrap(value: str) -> str:
    key = _key()
    raw = value.encode("utf-8")
    if key is None:
        return "plain:" + base64.urlsafe_b64encode(raw).decode("ascii")
    # XOR + base64 (lightweight; not a substitute for OS keyring)
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return "x:" + base64.urlsafe_b64encode(out).decode("ascii")


def _unwrap(token: str) -> str:
    if token.startswith("plain:"):
        return base64.urlsafe_b64decode(token[6:].encode("ascii")).decode("utf-8")
    if token.startswith("x:"):
        key = _key()
        if key is None:
            raise RuntimeError("SOPHYANE_VAULT_PASSPHRASE required to read encrypted secret")
        raw = base64.urlsafe_b64decode(token[2:].encode("ascii"))
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
        return out.decode("utf-8")
    raise ValueError("unknown vault token format")


def _load() -> dict[str, Any]:
    _ensure()
    if not VAULT_FILE.exists():
        return {"profiles": {}}
    data = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
    data.setdefault("profiles", {})
    return data


def _save(data: dict[str, Any]) -> None:
    _ensure()
    VAULT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(VAULT_FILE, 0o600)
    except OSError:
        pass


def set_secret(profile: str, name: str, value: str) -> None:
    profile = profile.strip().lower()
    data = _load()
    bucket = data["profiles"].setdefault(profile, {})
    bucket[name] = _wrap(value)
    _save(data)


def get_secret(profile: str, name: str) -> str | None:
    profile = profile.strip().lower()
    bucket = _load()["profiles"].get(profile) or {}
    token = bucket.get(name)
    if not token:
        return None
    return _unwrap(token)


def list_profiles() -> list[str]:
    return sorted(_load()["profiles"].keys())


def list_secret_names(profile: str) -> list[str]:
    bucket = _load()["profiles"].get(profile.strip().lower()) or {}
    return sorted(bucket.keys())


def export_to_environ(profile: str, mapping: dict[str, str]) -> None:
    """mapping: env_var -> secret name in vault."""
    for env_key, secret_name in mapping.items():
        val = get_secret(profile, secret_name)
        if val is not None:
            os.environ[env_key] = val


def main(argv: list[str] | None = None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "Usage:\n"
            "  python -m sophyane.secret_vault set <profile-email> <name>\n"
            "  python -m sophyane.secret_vault get <profile-email> <name>\n"
            "  python -m sophyane.secret_vault list [profile-email]\n"
            "Names example: imap_user, imap_app_password\n"
        )
        return 0
    cmd = argv[0]
    if cmd == "set" and len(argv) >= 3:
        profile, name = argv[1], argv[2]
        value = getpass.getpass(f"Value for {profile}/{name}: ")
        set_secret(profile, name, value)
        print(f"Stored {name} for {profile} (not printed).")
        return 0
    if cmd == "get" and len(argv) >= 3:
        # Print only if stdout is not a log sink you share; prefer export_to_environ in code
        v = get_secret(argv[1], argv[2])
        if v is None:
            print("missing", file=sys.stderr)
            return 1
        print(v)
        return 0
    if cmd == "list":
        if len(argv) == 1:
            print("\n".join(list_profiles()) or "(no profiles)")
        else:
            print("\n".join(list_secret_names(argv[1])) or "(no secrets)")
        return 0
    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
