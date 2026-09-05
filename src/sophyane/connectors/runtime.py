"""Load connector manifests and dispatch ops."""
from __future__ import annotations
import re

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

            sent_markers = (
                "outgoing",
                "sent email",
                "sent mail",
                "email i sent",
                "mail i sent",
            )
            wants_sent = any(marker in text for marker in sent_markers)

            # Never route a sent-mail request to the inbox latest operation.
            if wants_sent and op_name == "latest":
                score = 0

            # Strongly prefer the Sent mailbox operation.
            if wants_sent and op_name == "sent":
                score += 10
            if score == 0 and resources:
                if op_name == "latest" and any(
                    w in text for w in ("last", "latest", "what was")
                ):
                    score = 1
                elif op_name == "first" and any(
                    w in text for w in ("first", "earliest", "oldest")
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
                score += 1
            if op_name == "sent" and score > 0:
                score += 2  # prefer search over latest on ties
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

    email_resources = {
        "email",
        "mail",
        "gmail",
        "inbox",
    }

    is_email_request = any(
        word in text
        for word in email_resources
    )

    # Some natural mailbox-analysis requests omit the literal words
    # "email", "mail", "gmail", and "inbox". Recognize only narrow
    # email-conversation evidence patterns here. Do not treat the
    # generic word "message" alone as email, because other private
    # connectors may own SMS/WhatsApp/Telegram/etc.
    implicit_email_analysis_patterns = (
        r"\bmessages?\s+i\s+received\b.{0,80}\b(?:never|not)\s+replied\b",
        r"\breceived\s+messages?\b.{0,80}\b(?:never|not)\s+replied\b",
        r"\bmessages?\s+i\s+sent\b.{0,80}\bmessages?\s+i\s+received\b",
        r"\bmessages?\s+i\s+received\b.{0,80}\bmessages?\s+i\s+sent\b",
        r"\blater\s+sent\s+reply\s+from\s+me\b",
        r"\bsubsequently\s+replied\b",
    )

    implicit_email_analysis_request = any(
        re.search(pattern, text)
        for pattern in implicit_email_analysis_patterns
    )

    if not is_email_request:
        is_email_request = implicit_email_analysis_request

    # Outbound authority must require an explicit requested action.
    # Words such as "reply", "sent", or "forward" occurring as
    # evidence-analysis nouns/verbs must NOT imply permission to send.
    outbound_patterns = (
        r"\bsend\s+(?:an?\s+)?email\b",
        r"\bsend\s+(?:an?\s+)?mail\b",
        r"\bcompose\s+(?:an?\s+)?email\b",
        r"\bdraft\s+(?:an?\s+)?email\b",
        r"\bwrite\s+(?:an?\s+)?email\s+to\b",
        r"\breply\s+to\s+(?:this|the|an?)\s+(?:email|message)\b",
        r"\bforward\s+(?:this|the|an?)\s+(?:email|message)\b",
        r"\bemail\s+[^.?!]{1,100}\s+about\b",
        r"\bmail\s+[^.?!]{1,100}\s+about\b",
    )

    is_outbound_request = any(
        re.search(pattern, text)
        for pattern in outbound_patterns
    )

    if is_email_request and is_outbound_request:
        return (
            "Gmail IMAP here is read-only and cannot send messages.\n\n"
            "I can draft an email for you to paste into Gmail.\n"
            "For example: draft an email to Saudia about an Islamabad "
            "to San Francisco ticket next month with flexible dates."
        )

    # Complex analytical requests may be more efficiently
    # solved by an ephemeral deterministic program than by a
    # generic connector operation. The compiled task receives
    # no greater authority than the original read-only request.
    try:
        from sophyane.task_orchestrator import (
            try_compiled_task_reply,
        )

        compiled_reply = try_compiled_task_reply(
            message,
            profile=profile,
        )

        if compiled_reply is not None:
            return compiled_reply

    except Exception:
        # Compiler failure must never destroy the existing
        # deterministic connector path.
        pass

    match = resolve_connector_op(message, profile=profile)

    # Complex read-only mailbox analysis must take precedence over
    # simple "sent" or "search" phrase matches. For example,
    # "Search Inbox and Sent Mail ... did I later reply?" contains
    # the phrase "sent mail", but it is not asking for the latest
    # sent message.
    advanced_email_analysis_markers = (
        "inbox and sent",
        "search inbox and sent",
        "inspect my inbox and sent",
        "received count",
        "sent count",
        "most frequently by email",
        "classify my",
        "classify them",
        "classify emails",
        "classify received emails",
        "analyze my last 200 received emails",
        "analyze my received emails",
        "containing attachments",
        "email attachments",
        "reconstruct the thread",
        "thread chronologically",
        "cannot find a later sent reply",
        "whether i subsequently replied",
        "require action from me",
        "unresolved",
        "invoices",
        "receipts",
        "payment confirmations",
        "api keys",
        "credentials",
        "access tokens",
    )

    advanced_email_analysis_request = (
        implicit_email_analysis_request
        or any(
            marker in text
            for marker in advanced_email_analysis_markers
        )
    )

    if advanced_email_analysis_request and is_email_request:
        result = run_connector(
            "email.imap",
            "analyze",
            args={
                "query": message,
                "message": message,
            },
            profile=profile,
        )

    elif match is None:
        return None

    else:
        result = run_connector(
            match.connector_id,
            match.op,
            args={
                "query": message,
                "message": message,
            },
            profile=profile,
        )
    if not result.get("ok"):
        return result.get("message") or f"Connector error: {result.get('error')}"
    fmt = result.get("formatted")
    if isinstance(fmt, str) and fmt.strip():
        return fmt
    return json.dumps({k: v for k, v in result.items() if k != "raw"}, indent=2)[:4000]
