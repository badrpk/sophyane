"""Load connector manifests and dispatch ops."""
from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sophyane.secret_vault import get_secret

CONNECTORS_ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE = os.environ.get("SOPHYANE_VAULT_PROFILE", "badrpk@gmail.com")

ENV_ALIASES = {
    "imap_user": ("SOPHYANE_IMAP_USER",),
    "imap_app_password": ("SOPHYANE_IMAP_APP_PASSWORD",),
    "gemini_api_key": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


@dataclass(frozen=True)
class ConnectorOpMatch:
    connector_id: str
    op: str
    available: bool
    missing_keys: tuple[str, ...]
    title: str


def _iter_manifests() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(CONNECTORS_ROOT.glob("*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data["_dir"] = path.parent.name
        out.append(data)
    return out


def list_connectors() -> list[dict[str, Any]]:
    return [
        {
            "id": m.get("id"),
            "title": m.get("title"),
            "vault_keys": m.get("vault_keys", []),
            "ops": list((m.get("ops") or {}).keys()),
            "available": _available(m),
        }
        for m in _iter_manifests()
    ]


def _has_key(profile: str, key: str) -> bool:
    for env in ENV_ALIASES.get(key, ()):
        if os.environ.get(env):
            return True
    return bool(get_secret(profile, key))


def _available(manifest: dict[str, Any], profile: str | None = None) -> bool:
    profile = profile or DEFAULT_PROFILE
    keys = list(manifest.get("vault_keys") or [])
    if not keys:
        return True
    return all(_has_key(profile, k) for k in keys)


def _missing_keys(manifest: dict[str, Any], profile: str | None = None) -> tuple[str, ...]:
    profile = profile or DEFAULT_PROFILE
    return tuple(k for k in (manifest.get("vault_keys") or []) if not _has_key(profile, k))


def resolve_connector_op(message: str, profile: str | None = None) -> ConnectorOpMatch | None:
    text = " ".join(str(message or "").lower().split())
    if not text:
        return None

    # Outbound / compose is not the read-only IMAP connector.
    outbound_markers = (
        "send email",
        "send an email",
        "send a mail",
        "compose email",
        "write an email",
        "email to ",
        "mail to ",
        "draft an email",
        "draft email",
    )
    if any(p in text for p in outbound_markers) or (
        "send" in text
        and "email" in text
        and any(w in text for w in (" to ", "airline", "ticket", "booking", "ask for"))
    ):
        return None

    best: ConnectorOpMatch | None = None
    best_score = 0
    for manifest in _iter_manifests():
        cid = str(manifest.get("id") or "")
        title = str(manifest.get("title") or cid)
        resources = [h.lower() for h in (manifest.get("match_resources") or [])]
        if resources and not any(h in text for h in resources):
            continue
        for op_name, op_meta in (manifest.get("ops") or {}).items():
            hints = [h.lower() for h in ((op_meta or {}).get("match_hints") or [])]
            score = sum(1 for h in hints if h in text)
            if score == 0 and resources:
                if op_name == "latest" and any(
                    w in text for w in ("last", "latest", "what was")
                ):
                    score = 1
                elif op_name == "search" and any(
                    w in text
                    for w in (
                        "find",
                        "search",
                        "see",
                        "look",
                        "company",
                        "own",
                        "in my email",
                        "in my mail",
                    )
                ):
                    score = 2
            if op_name == "search" and score > 0:
                score += 1  # prefer search over latest on ties
            if score <= 0:
                continue
            if score > best_score:
                best_score = score
                best = ConnectorOpMatch(
                    connector_id=cid,
                    op=str(op_name),
                    available=_available(manifest, profile),
                    missing_keys=_missing_keys(manifest, profile),
                    title=title,
                )
    return best


def run_connector(
    connector_id: str,
    op: str,
    args: dict[str, Any] | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    profile = profile or DEFAULT_PROFILE
    manifest = next((m for m in _iter_manifests() if m.get("id") == connector_id), None)
    if not manifest:
        return {"ok": False, "error": "unknown_connector", "message": connector_id}
    if not _available(manifest, profile):
        missing = _missing_keys(manifest, profile)
        lines = [
            f"{manifest.get('title') or connector_id} is not configured.",
            "Store secrets in the vault (never in chat):",
        ]
        for k in missing:
            lines.append(
                f"  PYTHONPATH=src python3 -m sophyane.secret_vault set {profile} {k}"
            )
        return {
            "ok": False,
            "error": "not_configured",
            "message": "\n".join(lines),
            "missing_keys": list(missing),
        }
    module_name = str(
        manifest.get("module")
        or f"sophyane.connectors.{manifest.get('_dir')}.handler"
    )
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        return {"ok": False, "error": "import_failed", "message": str(e)}
    fn = getattr(mod, "execute", None)
    if not callable(fn):
        return {"ok": False, "error": "no_execute", "message": module_name}
    try:
        return fn(op=op, args=args or {}, profile=profile, manifest=manifest)
    except Exception as e:
        return {"ok": False, "error": "execute_failed", "message": str(e)}


def try_connector_reply(message: str, profile: str | None = None) -> str | None:
    text = " ".join(str(message or "").lower().split())

    outbound_email_words = {
        "send",
        "compose",
        "write",
        "draft",
        "reply",
        "forward",
        "email to",
        "mail to",
    }

    email_resources = {
        "email",
        "mail",
        "gmail",
        "inbox",
    }

    is_email_request = any(word in text for word in email_resources)
    is_outbound_request = any(word in text for word in outbound_email_words)

    if is_email_request and is_outbound_request:
        return (
            "Gmail IMAP here is read-only (cannot send).

I can draft a message for you to paste into Gmail.
Say: draft email to Saudia about ISB to SFO next month flexible dates."
            "It can read and search inbox messages, but it cannot "
            "send, reply to, forward, or compose email."
        )

    match = resolve_connector_op(message, profile=profile)
    if match is None:
        return None
    result = run_connector(
        match.connector_id,
        match.op,
        args={"query": message, "message": message},
        profile=profile,
    )
    if not result.get("ok"):
        return result.get("message") or f"Connector error: {result.get('error')}"
    fmt = result.get("formatted")
    if isinstance(fmt, str) and fmt.strip():
        return fmt
    return json.dumps({k: v for k, v in result.items() if k != "raw"}, indent=2)[:4000]
