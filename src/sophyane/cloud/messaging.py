"""Sophyane multi-channel messaging: Email (live), Telegram bot (live with token), WhatsApp (bridge).

Merchant defaults: badrpk@gmail.com · +923212558089

WhatsApp: queues to outbox + optional WhatsApp Cloud API / local bridge command.
Telegram: Bot API sendMessage + getUpdates long-poll helper.
Email: Gmail SMTP via ~/.shmry_email.env (already used for OTP).

Secrets: ~/.config/sophyane/messaging.env (mode 600) — never commit.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any
import threading
import math

MESSAGING_ENV = Path.home() / ".config" / "sophyane" / "messaging.env"
PAYMENTS_ENV = Path.home() / ".config" / "sophyane" / "payments.env"
SMTP_ENV = Path.home() / ".shmry_email.env"
WA_OUTBOX = Path.home() / ".local" / "state" / "sophyane" / "whatsapp_outbox" / "queue.jsonl"
_WHATSAPP_INBOUND_MAX_ATTEMPTS = 3
_whatsapp_inbound_retry_attempt_lock = threading.Lock()

WHATSAPP_INBOUND_SPOOL = (
    Path.home()
    / ".local"
    / "state"
    / "sophyane"
    / "whatsapp_inbound"
)
TG_STATE = Path.home() / ".local" / "state" / "sophyane" / "telegram_state.json"

DEFAULT_EMAIL = "badrpk@gmail.com"
DEFAULT_PHONE = "+923212558089"
DEFAULT_WA = "923212558089"


def _parse_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_messaging_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for prefix in ("TELEGRAM_", "WHATSAPP_", "SMS_", "MERCHANT_", "MESSAGING_"):
        for k, v in os.environ.items():
            if k.startswith(prefix):
                env[k] = v.strip()
    env.update(_parse_env(PAYMENTS_ENV))
    env.update(_parse_env(MESSAGING_ENV))
    env.update(_parse_env(SMTP_ENV))
    return env


def merchant_contacts(env: dict[str, str] | None = None) -> dict[str, str]:
    e = env or load_messaging_env()
    return {
        "name": e.get("MERCHANT_NAME") or "Badar Uzaman",
        "email": e.get("MERCHANT_EMAIL") or e.get("SMTP_USER") or DEFAULT_EMAIL,
        "phone": e.get("MERCHANT_PHONE") or DEFAULT_PHONE,
        "phone_local": e.get("MERCHANT_PHONE_LOCAL") or "03212558089",
        "whatsapp": (e.get("MERCHANT_WHATSAPP") or e.get("WHATSAPP_OWNER") or DEFAULT_WA).replace("+", "").replace(" ", ""),
        "telegram_user": e.get("TELEGRAM_OWNER_USERNAME") or "",
        "telegram_chat_id": e.get("TELEGRAM_OWNER_CHAT_ID") or "",
    }


def public_status() -> dict[str, Any]:
    e = load_messaging_env()
    m = merchant_contacts(e)
    tg_token = bool((e.get("TELEGRAM_BOT_TOKEN") or "").strip())
    wa_cloud = bool((e.get("WHATSAPP_CLOUD_TOKEN") or "").strip() and (e.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip())
    wa_cmd = bool((e.get("WHATSAPP_SEND_CMD") or "").strip())
    wa_native_agent = bool(
        (e.get("WHATSAPP_AGENT_API_KEY") or "").strip()
    )
    smtp_ok = bool((e.get("SMTP_USER") or "").strip() and (e.get("SMTP_PASS") or "").strip())
    channels = {
        "email": {"enabled": smtp_ok, "from": e.get("SMTP_USER") or m["email"], "status": "live" if smtp_ok else "needs_smtp"},
        "telegram": {
            "enabled": tg_token,
            "bot_username": e.get("TELEGRAM_BOT_USERNAME") or "",
            "owner_chat_id": m["telegram_chat_id"],
            "status": "live" if tg_token else "needs_bot_token",
            "hint": ("Users message @" + (e.get("TELEGRAM_BOT_USERNAME") or "sophyanebot") + " for chat + alerts") if tg_token else "Set TELEGRAM_BOT_TOKEN in messaging.env",
        },
        "whatsapp": {
            "enabled": wa_cloud or wa_cmd or wa_native_agent,
            "owner": m["whatsapp"],
            "mode": (
                "cloud_api"
                if wa_cloud
                else (
                    "local_cmd"
                    if wa_cmd
                    else (
                        "native_agent"
                        if wa_native_agent
                        else "outbox_only"
                    )
                )
            ),
            "status": (
                "live"
                if (wa_cloud or wa_cmd)
                else (
                    "needs_transport"
                    if wa_native_agent
                    else "needs_bridge"
                )
            ),
            "hint": (
                "Option A: WhatsApp Cloud API (WHATSAPP_CLOUD_TOKEN + WHATSAPP_PHONE_NUMBER_ID). "
                "Option B: install wacli and set WHATSAPP_SEND_CMD. "
                "Option C: messages queue to outbox until bridge is linked."
            ),
            "outbox": str(WA_OUTBOX),
        },
        "sms": {
            "enabled": bool(e.get("TWILIO_ACCOUNT_SID") and e.get("TWILIO_AUTH_TOKEN") and e.get("TWILIO_FROM")),
            "status": "live" if (e.get("TWILIO_ACCOUNT_SID") and e.get("TWILIO_AUTH_TOKEN")) else "needs_twilio",
            "hint": "Optional: set TWILIO_* in messaging.env for SMS on your behalf",
        },
    }
    return {
        "ok": True,
        "merchant": m,
        "channels": channels,
        "ready": [k for k, v in channels.items() if v.get("enabled")],
        "note": "Sophyane can email now; Telegram goes live with bot token; WhatsApp needs Cloud API or wacli link.",
    }


# ── Email ───────────────────────────────────────────────────────────────────


def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    reply_to: str | None = None,
) -> dict[str, Any]:
    e = load_messaging_env()
    host = e.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(e.get("SMTP_PORT") or "587")
    user = e.get("SMTP_USER") or ""
    password = (e.get("SMTP_PASS") or "").replace(" ", "")
    from_addr = e.get("SMTP_FROM") or user
    if not user or not password:
        return {"ok": False, "error": "SMTP not configured (~/.shmry_email.env)"}
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=45) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True, "channel": "email", "to": to, "from": from_addr}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err), "channel": "email"}


# ── Telegram ────────────────────────────────────────────────────────────────


def _tg_api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call Telegram Bot API. Direct → pinned IPv4 → Tor SOCKS (common on blocked nets)."""
    import subprocess
    import tempfile

    e = load_messaging_env()
    token = (e.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in messaging.env")
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload or {})
    timeout = int(e.get("TELEGRAM_HTTP_TIMEOUT") or "45")

    def _via_curl(extra: list[str]) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write(body)
            tf.flush()
            path = tf.name
        try:
            cmd = [
                "curl",
                "-sS",
                "-m",
                str(timeout),
                "-X",
                "POST",
                url,
                "-H",
                "Content-Type: application/json",
                "-H",
                "User-Agent: SophyaneBot/17.3",
                "--data-binary",
                f"@{path}",
                *extra,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout or f"curl exit {r.returncode}")[:300])
            return json.loads(r.stdout or "{}")
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    errors: list[str] = []
    # 1) Direct IPv4
    try:
        return _via_curl(["-4"])
    except Exception as err:
        errors.append(f"direct4:{err}")
    # 2) Pin known Telegram API edge IPs (bypass bad DNS/IPv6)
    for ip in (e.get("TELEGRAM_API_IP") or "149.154.167.220,149.154.167.50,149.154.166.110").split(","):
        ip = ip.strip()
        if not ip:
            continue
        try:
            return _via_curl(["-4", "--resolve", f"api.telegram.org:443:{ip}"])
        except Exception as err:
            errors.append(f"ip{ip}:{err}")
    # 3) Tor SOCKS (local tor on 9050)
    socks = (e.get("TELEGRAM_SOCKS") or "127.0.0.1:9050").strip()
    if socks:
        try:
            return _via_curl(["--socks5-hostname", socks])
        except Exception as err:
            errors.append(f"socks:{err}")
    # 4) Last resort: urllib (may hang on IPv6)
    try:
        data = body.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "SophyaneBot/17.3"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=min(timeout, 20)) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        errors.append(f"urllib:{err}")
    raise RuntimeError("Telegram API unreachable: " + " | ".join(errors)[:500])


def telegram_get_me() -> dict[str, Any]:
    try:
        data = _tg_api("getMe")
        if data.get("ok"):
            result = data.get("result") or {}
            return {"ok": True, "bot": result}
        return {"ok": False, "error": data}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err)}


def send_telegram(text: str, *, chat_id: str | None = None, parse_mode: str = "") -> dict[str, Any]:
    e = load_messaging_env()
    cid = (chat_id or e.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    if not cid:
        return {
            "ok": False,
            "error": "TELEGRAM_OWNER_CHAT_ID not set. Message your bot once, then run discover_telegram_chat.",
            "channel": "telegram",
        }
    payload: dict[str, Any] = {"chat_id": cid, "text": text[:4000]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        data = _tg_api("sendMessage", payload)
        if data.get("ok"):
            return {"ok": True, "channel": "telegram", "chat_id": cid, "message_id": (data.get("result") or {}).get("message_id")}
        return {"ok": False, "error": str(data), "channel": "telegram"}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err), "channel": "telegram"}


def discover_telegram_chat() -> dict[str, Any]:
    """Read getUpdates and pick latest private chat (owner)."""
    try:
        data = _tg_api("getUpdates", {"timeout": 0, "limit": 50})
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err)}
    if not data.get("ok"):
        return {"ok": False, "error": str(data)}
    chats: list[dict[str, Any]] = []
    for upd in data.get("result") or []:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if not chat:
            continue
        chats.append(
            {
                "chat_id": chat.get("id"),
                "type": chat.get("type"),
                "username": chat.get("username"),
                "first_name": chat.get("first_name"),
                "text": (msg.get("text") or "")[:80],
                "update_id": upd.get("update_id"),
            }
        )
    private = [c for c in chats if c.get("type") == "private"]
    chosen = private[-1] if private else (chats[-1] if chats else None)
    if chosen and chosen.get("chat_id") is not None:
        # persist
        _upsert_messaging_env("TELEGRAM_OWNER_CHAT_ID", str(chosen["chat_id"]))
        if chosen.get("username"):
            _upsert_messaging_env("TELEGRAM_OWNER_USERNAME", str(chosen["username"]))
        TG_STATE.parent.mkdir(parents=True, exist_ok=True)
        TG_STATE.write_text(json.dumps({"owner_chat": chosen, "ts": time.time()}, indent=2), encoding="utf-8")
        return {"ok": True, "chat": chosen, "saved": True}
    return {
        "ok": False,
        "error": "No chats yet. Open Telegram, find your bot, send /start, then retry.",
        "updates": len(data.get("result") or []),
    }


def _upsert_messaging_env(key: str, value: str) -> None:
    MESSAGING_ENV.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if MESSAGING_ENV.exists():
        for line in MESSAGING_ENV.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    MESSAGING_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(MESSAGING_ENV, 0o600)
    except OSError:
        pass


# ── WhatsApp ────────────────────────────────────────────────────────────────


def send_whatsapp(to: str, text: str) -> dict[str, Any]:
    e = load_messaging_env()
    to_clean = "".join(c for c in to if c.isdigit())
    text = text[:4000]

    # 1) Meta Cloud API
    token = (e.get("WHATSAPP_CLOUD_TOKEN") or "").strip()
    phone_id = (e.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    if token and phone_id:
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_clean,
            "type": "text",
            "text": {"body": text},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "SophyaneWA/17.3",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            return {"ok": True, "channel": "whatsapp", "mode": "cloud_api", "to": to_clean, "result": data}
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "error": str(err), "channel": "whatsapp", "mode": "cloud_api"}

    # 2) Local command bridge (wacli / custom / Sophyane wa_send.sh)
    cmd = (e.get("WHATSAPP_SEND_CMD") or "").strip()
    if cmd:
        import shlex
        import subprocess

        try:
            # Prefer explicit placeholders with argv (spaces-safe)
            if "{to}" in cmd and "{msg}" in cmd:
                # e.g. "/path/wa_send.sh {to} {msg}" → [script, phone, text]
                prefix = cmd.split("{to}")[0].strip()
                script = shlex.split(prefix)[0] if prefix else cmd
                args = [script, to_clean, text]
            else:
                args = shlex.split(cmd) + [to_clean, text]
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return {"ok": True, "channel": "whatsapp", "mode": "local_cmd", "to": to_clean, "stdout": (r.stdout or "")[:300]}
            return {"ok": False, "error": (r.stderr or r.stdout or f"exit {r.returncode}")[:400], "channel": "whatsapp"}
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "error": str(err), "channel": "whatsapp", "mode": "local_cmd"}

    # 2b) Built-in HTTP bridge (Sophyane messaging-bridge on :8791)
    try:
        payload = json.dumps({"to": to_clean, "text": text}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8791/send",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            return {"ok": True, "channel": "whatsapp", "mode": "http_bridge", "to": to_clean, "result": data}
        # if not ready, fall through to outbox
        if "not linked" in str(data.get("error") or "").lower() or "scan" in str(data.get("error") or "").lower():
            pass
        else:
            return {"ok": False, "error": str(data.get("error") or data), "channel": "whatsapp", "mode": "http_bridge"}
    except Exception:
        pass

    # 3) Queue outbox for later drain when bridge is linked
    WA_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    job = {
        "to": to_clean,
        "body": text,
        "status": "QUEUED",
        "ts": time.time(),
        "source": "sophyane",
    }
    with WA_OUTBOX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(job, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "queued": True,
        "channel": "whatsapp",
        "mode": "outbox",
        "to": to_clean,
        "message": f"Queued to {WA_OUTBOX}. Link WhatsApp Cloud API or wacli to actually deliver.",
    }


# ── SMS (Twilio optional) ───────────────────────────────────────────────────


def send_sms(to: str, text: str) -> dict[str, Any]:
    e = load_messaging_env()
    sid = (e.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (e.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (e.get("TWILIO_FROM") or "").strip()
    if not (sid and token and from_num):
        return {"ok": False, "error": "Twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM)", "channel": "sms"}
    to_e164 = to if to.startswith("+") else ("+" + "".join(c for c in to if c.isdigit()))
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    body = urllib.parse.urlencode({"To": to_e164, "From": from_num, "Body": text[:1500]}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    import base64

    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return {"ok": True, "channel": "sms", "sid": data.get("sid"), "to": to_e164}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err), "channel": "sms"}


# ── Unified notify ──────────────────────────────────────────────────────────


def notify_owner(text: str, *, channels: list[str] | None = None) -> dict[str, Any]:
    """Send to merchant on selected channels (default: all ready)."""
    e = load_messaging_env()
    m = merchant_contacts(e)
    st = public_status()
    ready = set(st.get("ready") or [])
    want = channels or list(ready) or ["email"]
    results: dict[str, Any] = {}
    if "email" in want:
        results["email"] = send_email(m["email"], "Sophyane notification", text)
    if "telegram" in want:
        results["telegram"] = send_telegram(text)
    if "whatsapp" in want:
        results["whatsapp"] = send_whatsapp(m["whatsapp"], text)
    if "sms" in want:
        results["sms"] = send_sms(m["phone"], text)
    ok_any = any(isinstance(v, dict) and v.get("ok") for v in results.values())
    return {"ok": ok_any, "merchant": m, "results": results}


def send_provider_update_request(
    *,
    provider: str,
    support_email: str,
    account_email: str = DEFAULT_EMAIL,
    new_phone: str = DEFAULT_PHONE,
) -> dict[str, Any]:
    """Email a service provider (or user as CC path) requesting contact update."""
    m = merchant_contacts()
    subject = f"Account contact update request — {provider} — {account_email}"
    body = f"""Hello {provider} Support,

Please update the registered contact details on my account:

  Account email (primary): {account_email}
  Full name: {m['name']}
  Mobile / WhatsApp (new): {new_phone}
  Local format (PK): {m['phone_local']}

Please confirm once email and phone/WhatsApp are aligned to the above.
This request is authorized by the account holder.

Thank you,
{m['name']}
{account_email}
{new_phone}
"""
    # Prefer sending to support; also send copy to owner
    to_support = send_email(support_email, subject, body, reply_to=account_email)
    to_owner = send_email(
        account_email,
        f"[Copy] {subject}",
        "Copy of provider request sent to " + support_email + "\n\n" + body,
    )
    return {"ok": to_support.get("ok") or to_owner.get("ok"), "support": to_support, "owner_copy": to_owner, "provider": provider}



def verify_whatsapp_webhook_signature(
    raw_body: bytes,
    supplied_signature: str,
) -> bool:
    """Verify Meta's WhatsApp webhook signature over exact request bytes."""
    import hashlib
    import hmac
    import os

    app_secret = (load_messaging_env().get("WHATSAPP_APP_SECRET") or "").strip()

    # Compatibility mode until an app secret is configured.
    if not app_secret:
        return True

    prefix = "sha256="
    if not supplied_signature.startswith(prefix):
        return False

    supplied_digest = supplied_signature[len(prefix):]

    if (
        len(supplied_digest) != 64
        or any(
            char not in "0123456789abcdefABCDEF"
            for char in supplied_digest
        )
    ):
        return False

    expected_digest = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected_digest,
        supplied_digest.lower(),
    )


def verify_whatsapp_webhook_request(request_path: str) -> str | None:
    """Return Meta's challenge when WhatsApp webhook verification succeeds."""
    import os
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(request_path).query)

    mode = query.get("hub.mode", [""])[0]
    supplied_token = query.get("hub.verify_token", [""])[0]
    challenge = query.get("hub.challenge", [""])[0]
    expected_token = (load_messaging_env().get("WHATSAPP_VERIFY_TOKEN") or "").strip()

    if (
        mode == "subscribe"
        and expected_token
        and supplied_token == expected_token
    ):
        return challenge

    return None



_WHATSAPP_INBOUND_IDEMPOTENCY_LIMIT = 4096
_whatsapp_inbound_completed: dict[str, None] = {}
_whatsapp_inbound_inflight: set[str] = set()


def _whatsapp_inbound_idempotency_lock():
    import threading

    lock = getattr(
        _whatsapp_inbound_idempotency_lock,
        "_lock",
        None,
    )
    if lock is None:
        lock = threading.Lock()
        _whatsapp_inbound_idempotency_lock._lock = lock
    return lock


def _reset_whatsapp_inbound_idempotency_for_tests() -> None:
    """Reset process-local WhatsApp idempotency state for tests."""
    with _whatsapp_inbound_idempotency_lock():
        _whatsapp_inbound_completed.clear()
        _whatsapp_inbound_inflight.clear()


def _begin_whatsapp_inbound(message_id: str) -> bool:
    """Claim a wamid; return False when already completed/in flight."""
    if not message_id:
        return True

    with _whatsapp_inbound_idempotency_lock():
        if (
            message_id in _whatsapp_inbound_completed
            or message_id in _whatsapp_inbound_inflight
        ):
            return False

        _whatsapp_inbound_inflight.add(message_id)
        return True


def _finish_whatsapp_inbound(
    message_id: str,
    *,
    success: bool,
) -> None:
    """Release a claim and remember only successful delivery."""
    if not message_id:
        return

    with _whatsapp_inbound_idempotency_lock():
        _whatsapp_inbound_inflight.discard(message_id)

        if not success:
            return

        _whatsapp_inbound_completed[message_id] = None

        while (
            len(_whatsapp_inbound_completed)
            > _WHATSAPP_INBOUND_IDEMPOTENCY_LIMIT
        ):
            oldest = next(iter(_whatsapp_inbound_completed))
            del _whatsapp_inbound_completed[oldest]


def _whatsapp_conversation_reply(message: str) -> str:
    """Generate a WhatsApp reply through the existing chat behavior."""
    from sophyane.cloud.telegram_bot import _chat_reply

    return _chat_reply(
        message,
        email="",
        plan="free",
    )


def _create_whatsapp_inbound_executor():
    from concurrent.futures import ThreadPoolExecutor

    return ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="sophyane-whatsapp-inbound",
    )


_whatsapp_inbound_executor = (
    _create_whatsapp_inbound_executor()
)
_whatsapp_inbound_futures: set = set()


def _whatsapp_inbound_futures_lock():
    import threading

    lock = getattr(
        _whatsapp_inbound_futures_lock,
        "_lock",
        None,
    )

    if lock is None:
        lock = threading.Lock()
        _whatsapp_inbound_futures_lock._lock = lock

    return lock


def _track_whatsapp_inbound_future(future) -> None:
    with _whatsapp_inbound_futures_lock():
        _whatsapp_inbound_futures.add(future)


def _untrack_whatsapp_inbound_future(future) -> None:
    with _whatsapp_inbound_futures_lock():
        _whatsapp_inbound_futures.discard(future)


def _snapshot_whatsapp_inbound_futures() -> tuple:
    with _whatsapp_inbound_futures_lock():
        return tuple(_whatsapp_inbound_futures)


def _clear_whatsapp_inbound_futures() -> None:
    with _whatsapp_inbound_futures_lock():
        _whatsapp_inbound_futures.clear()

_WHATSAPP_INBOUND_ADMISSION_LIMIT = 4096
_whatsapp_inbound_admitted: dict[str, None] = {}

_WHATSAPP_INBOUND_PENDING_LIMIT = 64
_whatsapp_inbound_pending = 0


def _whatsapp_inbound_capacity_lock():
    """Return the process-local inbound capacity lock."""
    import threading

    lock = getattr(
        _whatsapp_inbound_capacity_lock,
        "_lock",
        None,
    )

    if lock is None:
        lock = threading.Lock()
        _whatsapp_inbound_capacity_lock._lock = lock

    return lock


def _claim_whatsapp_inbound_capacity() -> bool:
    """Reserve one active-or-pending worker slot."""
    global _whatsapp_inbound_pending

    with _whatsapp_inbound_capacity_lock():
        if (
            _whatsapp_inbound_pending
            >= _WHATSAPP_INBOUND_PENDING_LIMIT
        ):
            return False

        _whatsapp_inbound_pending += 1
        return True


def _release_whatsapp_inbound_capacity() -> None:
    """Release one active-or-pending worker slot."""
    global _whatsapp_inbound_pending

    with _whatsapp_inbound_capacity_lock():
        if _whatsapp_inbound_pending > 0:
            _whatsapp_inbound_pending -= 1


def _reset_whatsapp_inbound_capacity_for_tests() -> None:
    """Reset process-local worker capacity state."""
    global _whatsapp_inbound_pending

    with _whatsapp_inbound_capacity_lock():
        _whatsapp_inbound_pending = 0


def _whatsapp_inbound_spool_path(
    message_id: str,
) -> Path:
    """Return the durable path for one inbound WhatsApp job."""
    import hashlib

    digest = hashlib.sha256(
        message_id.encode("utf-8")
    ).hexdigest()

    return WHATSAPP_INBOUND_SPOOL / f"{digest}.json"


def _fsync_whatsapp_inbound_directory() -> None:
    """Durably commit inbound spool directory metadata."""
    import os

    descriptor = os.open(
        WHATSAPP_INBOUND_SPOOL,
        os.O_RDONLY,
    )

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _WhatsAppInboundCommitUncertainError(OSError):
    """This attempt replaced its spool target before persistence failed."""


def _persist_whatsapp_inbound_message(
    message: dict[str, str],
) -> Path:
    """Atomically persist one inbound job before worker submission."""
    import os
    import tempfile

    message_copy = dict(message)
    message_id = str(
        message_copy.get("message_id") or ""
    )

    WHATSAPP_INBOUND_SPOOL.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = _whatsapp_inbound_spool_path(
        message_id
    )

    payload = {
        "message": message_copy,
        "attempts": 0,
    }

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".whatsapp-inbound-",
        suffix=".tmp",
        dir=WHATSAPP_INBOUND_SPOOL,
    )

    temporary = Path(temporary_name)
    replaced = False

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(
            temporary,
            target,
        )
        replaced = True
        _fsync_whatsapp_inbound_directory()

    except Exception as exc:
        try:
            temporary.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        if replaced:
            raise _WhatsAppInboundCommitUncertainError(str(exc)) from exc
        raise

    return target


def _recover_whatsapp_inbound_spool() -> list[dict[str, str]]:
    """Discover durable inbound jobs and restore admission state."""
    recovered: list[dict[str, str]] = []

    if not WHATSAPP_INBOUND_SPOOL.exists():
        return recovered

    for path in sorted(
        WHATSAPP_INBOUND_SPOOL.glob("*.json")
    ):
        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        message = payload.get("message")

        if not isinstance(message, dict):
            continue

        message_id = message.get("message_id")
        sender = message.get("sender")
        text = message.get("text")

        if not all(
            isinstance(item, str) and item
            for item in (
                message_id,
                sender,
                text,
            )
        ):
            continue

        normalized = {
            "message_id": message_id,
            "sender": sender,
            "text": text,
        }

        recovered.append(
            normalized
        )

        if message_id:
            _claim_whatsapp_inbound_admission(
                message_id
            )

    return recovered


def _remove_whatsapp_inbound_message(
    message_id: str,
) -> None:
    """Remove one durable inbound job after terminal success."""
    if not message_id:
        return

    path = _whatsapp_inbound_spool_path(
        message_id
    )

    try:
        path.unlink(
            missing_ok=True
        )
    except FileNotFoundError:
        pass


def _replay_whatsapp_inbound_spool() -> list[dict]:
    """Submit already-durable inbound jobs after restart."""
    recovered = _recover_whatsapp_inbound_spool()
    results: list[dict] = []

    for message in recovered:
        message_copy = dict(message)
        message_id = str(
            message_copy.get("message_id") or ""
        )
        sender = str(
            message_copy.get("sender") or ""
        )
        attempts = 0
        next_attempt_at = 0.0

        durable_path = _whatsapp_inbound_spool_path(
            message_id
        )

        try:
            durable_payload = json.loads(
                durable_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            durable_payload = {}

        if isinstance(durable_payload, dict):
            durable_attempts = durable_payload.get(
                "attempts",
                0,
            )

            if (
                not isinstance(durable_attempts, bool)
                and isinstance(durable_attempts, int)
                and durable_attempts >= 0
            ):
                attempts = durable_attempts

            durable_next_attempt_at = durable_payload.get(
                "next_attempt_at",
                0.0,
            )

            if (
                not isinstance(durable_next_attempt_at, bool)
                and isinstance(
                    durable_next_attempt_at,
                    (int, float),
                )
                and math.isfinite(
                    durable_next_attempt_at
                )
                and durable_next_attempt_at > 0
            ):
                next_attempt_at = float(
                    durable_next_attempt_at
                )

        if attempts >= _WHATSAPP_INBOUND_MAX_ATTEMPTS:
            _release_whatsapp_inbound_admission(
                message_id
            )

            results.append(
                {
                    "ok": False,
                    "queued": False,
                    "message_id": message_id,
                    "sender": sender,
                    "stage": "retry_exhausted",
                    "attempts": attempts,
                }
            )
            continue

        if next_attempt_at > time.time():
            _release_whatsapp_inbound_admission(
                message_id
            )

            results.append(
                {
                    "ok": False,
                    "queued": False,
                    "message_id": message_id,
                    "sender": sender,
                    "stage": "retry_backoff",
                    "attempts": attempts,
                    "next_attempt_at": next_attempt_at,
                }
            )
            continue

        if not _claim_whatsapp_inbound_capacity():
            _release_whatsapp_inbound_admission(
                message_id
            )

            results.append(
                {
                    "ok": False,
                    "queued": False,
                    "message_id": message_id,
                    "sender": sender,
                    "stage": "backpressure",
                    "error": "WhatsApp inbound worker capacity exhausted",
                }
            )
            continue

        try:
            future = _whatsapp_inbound_executor.submit(
                process_whatsapp_inbound_message,
                message_copy,
            )
        except Exception as exc:
            _release_whatsapp_inbound_capacity()
            _release_whatsapp_inbound_admission(
                message_id
            )

            results.append(
                {
                    "ok": False,
                    "queued": False,
                    "message_id": message_id,
                    "sender": sender,
                    "stage": "handoff",
                    "error": str(exc),
                }
            )
            continue

        _track_whatsapp_inbound_future(
            future
        )

        try:
            future.add_done_callback(
                _whatsapp_inbound_completion_callback(
                    message_id
                )
            )
        except Exception:
            _untrack_whatsapp_inbound_future(
                future
            )
            _release_whatsapp_inbound_capacity()
            _release_whatsapp_inbound_admission(
                message_id
            )

        results.append(
            {
                "ok": True,
                "queued": True,
                "message_id": message_id,
                "sender": sender,
            }
        )

    return results

def _retry_whatsapp_inbound_spool() -> list[dict]:
    """Retry durable inbound jobs while the process remains alive."""
    return _replay_whatsapp_inbound_spool()




def _whatsapp_inbound_admission_lock():
    import threading

    lock = getattr(
        _whatsapp_inbound_admission_lock,
        "_lock",
        None,
    )

    if lock is None:
        lock = threading.Lock()
        _whatsapp_inbound_admission_lock._lock = lock

    return lock


def _claim_whatsapp_inbound_admission(
    message_id: str,
) -> bool:
    """Claim one wamid at the handoff boundary."""
    if not message_id:
        return True

    with _whatsapp_inbound_admission_lock():
        if message_id in _whatsapp_inbound_admitted:
            return False

        _whatsapp_inbound_admitted[message_id] = None

        while (
            len(_whatsapp_inbound_admitted)
            > _WHATSAPP_INBOUND_ADMISSION_LIMIT
        ):
            oldest = next(
                iter(_whatsapp_inbound_admitted)
            )
            del _whatsapp_inbound_admitted[oldest]

        return True


def _release_whatsapp_inbound_admission(
    message_id: str,
) -> None:
    """Release a claim when executor submission did not succeed."""
    if not message_id:
        return

    with _whatsapp_inbound_admission_lock():
        _whatsapp_inbound_admitted.pop(
            message_id,
            None,
        )


def _reset_whatsapp_inbound_admission_for_tests() -> None:
    """Reset process-local handoff admission state."""
    with _whatsapp_inbound_admission_lock():
        _whatsapp_inbound_admitted.clear()


def _whatsapp_inbound_future_done(future) -> None:
    """Forget completed inbound work and release worker capacity."""
    _untrack_whatsapp_inbound_future(future)
    _release_whatsapp_inbound_capacity()

    try:
        future.exception()
    except Exception:
        # The HTTP acknowledgement is already independent from
        # background execution. This callback is final containment.
        pass


def _record_whatsapp_inbound_failed_attempt(
    message_id: str,
) -> None:
    """Durably consume one failed processing attempt."""
    import os
    import tempfile

    path = _whatsapp_inbound_spool_path(
        message_id
    )

    with _whatsapp_inbound_retry_attempt_lock:
        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        message = payload.get("message")

        if not isinstance(message, dict):
            return

        attempts = payload.get(
            "attempts",
            0,
        )

        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 0
        ):
            attempts = 0

        payload["attempts"] = attempts + 1
        payload["next_attempt_at"] = time.time() + 1.0

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".whatsapp-inbound-retry-",
            suffix=".tmp",
            dir=path.parent,
        )

        temporary = Path(
            temporary_name
        )

        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as stream:
                json.dump(
                    payload,
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(
                    stream.fileno()
                )

            os.replace(
                temporary,
                path,
            )
            _fsync_whatsapp_inbound_directory()

        except Exception:
            try:
                temporary.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

            raise


def _whatsapp_inbound_completion_callback(
    message_id: str,
):
    """Bind one admitted message ID to worker completion."""

    def completed(future) -> None:
        failed = False

        try:
            result = future.result()
            failed = not (
                isinstance(result, dict)
                and result.get("ok") is True
            )
        except Exception:
            failed = True

        try:
            if failed:
                try:
                    _record_whatsapp_inbound_failed_attempt(
                        message_id
                    )
                except Exception:
                    pass
                finally:
                    _release_whatsapp_inbound_admission(
                        message_id
                    )
        finally:
            _whatsapp_inbound_future_done(future)

    return completed


def _drain_whatsapp_inbound_worker_for_tests() -> None:
    """Wait for currently submitted WhatsApp inbound work."""
    from concurrent.futures import wait

    pending = _snapshot_whatsapp_inbound_futures()

    if pending:
        wait(pending)


def _reset_whatsapp_inbound_worker_for_tests() -> None:
    """Replace the shared inbound executor deterministically for tests."""
    global _whatsapp_inbound_executor

    old_executor = _whatsapp_inbound_executor

    old_executor.shutdown(wait=True)

    _clear_whatsapp_inbound_futures()
    _reset_whatsapp_inbound_capacity_for_tests()

    _whatsapp_inbound_executor = (
        _create_whatsapp_inbound_executor()
    )


def enqueue_whatsapp_inbound_message(
    message: dict[str, str],
) -> dict:
    """Hand one inbound WhatsApp message to bounded background work."""
    message_copy = dict(message)
    message_id = str(message_copy.get("message_id") or "")
    sender = str(message_copy.get("sender") or "")

    if not message_id:
        return {
            "ok": False,
            "queued": False,
            "message_id": message_id,
            "sender": sender,
            "stage": "handoff",
            "error": "WhatsApp inbound message_id is required",
        }

    if not _claim_whatsapp_inbound_admission(
        message_id
    ):
        return {
            "ok": True,
            "queued": False,
            "duplicate": True,
            "message_id": message_id,
            "sender": sender,
        }

    try:
        _persist_whatsapp_inbound_message(
            message_copy
        )
    except Exception as exc:
        durable_evidence = isinstance(
            exc, _WhatsAppInboundCommitUncertainError
        )

        _release_whatsapp_inbound_admission(
            message_id
        )

        return {
            "ok": False,
            "queued": False,
            "message_id": message_id,
            "sender": sender,
            "stage": (
                "durability_uncertain"
                if durable_evidence
                else "handoff"
            ),
            "durable_evidence": durable_evidence,
            "error": str(exc),
        }

    if not _claim_whatsapp_inbound_capacity():
        _release_whatsapp_inbound_admission(
            message_id
        )

        return {
            "ok": False,
            "queued": False,
            "message_id": message_id,
            "sender": sender,
            "stage": "backpressure",
            "error": "WhatsApp inbound worker capacity exhausted",
        }

    try:
        future = _whatsapp_inbound_executor.submit(
            process_whatsapp_inbound_message,
            message_copy,
        )
    except Exception as exc:
        _release_whatsapp_inbound_capacity()
        _release_whatsapp_inbound_admission(
            message_id
        )

        return {
            "ok": False,
            "queued": False,
            "message_id": message_id,
            "sender": sender,
            "stage": "handoff",
            "error": str(exc),
        }

    _track_whatsapp_inbound_future(future)

    try:
        future.add_done_callback(
            _whatsapp_inbound_completion_callback(
                message_id
            )
        )
    except Exception:
        # Submission succeeded, but without a completion callback
        # this process cannot safely retain lifecycle ownership.
        # Keep the durable job recoverable and release only the
        # process-local tracking, capacity, and admission claims.
        _untrack_whatsapp_inbound_future(
            future
        )
        _release_whatsapp_inbound_capacity()
        _release_whatsapp_inbound_admission(
            message_id
        )

    return {
        "ok": True,
        "queued": True,
        "message_id": message_id,
        "sender": sender,
    }


def process_whatsapp_inbound_message(
    message: dict[str, str],
) -> dict:
    """Generate and send the reply for one parsed WhatsApp text message."""
    message_id = str(message.get("message_id") or "")
    sender = str(message.get("sender") or "")
    text = str(message.get("text") or "")

    if not _begin_whatsapp_inbound(message_id):
        return {
            "ok": True,
            "message_id": message_id,
            "sender": sender,
            "duplicate": True,
        }

    success = False

    try:
        try:
            reply = _whatsapp_conversation_reply(text)
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "message_id": message_id,
                "sender": sender,
                "stage": "conversation",
                "error": str(err),
            }

        try:
            sent = send_whatsapp(
                sender,
                reply,
            )
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "message_id": message_id,
                "sender": sender,
                "reply": reply,
                "stage": "send",
                "error": str(err),
            }

        success = bool(sent.get("ok"))

        if success:
            _remove_whatsapp_inbound_message(
                message_id
            )

        result = {
            "ok": success,
            "message_id": message_id,
            "sender": sender,
            "reply": reply,
            "send": sent,
        }

        if not success:
            result["stage"] = "send"

        return result

    finally:
        _finish_whatsapp_inbound(
            message_id,
            success=success,
        )


def validate_whatsapp_webhook_envelope(payload: dict) -> bool:
    """Validate the outer Meta WhatsApp webhook event structure."""
    if payload.get("object") != "whatsapp_business_account":
        return False

    entries = payload.get("entry")
    if not isinstance(entries, list) or not entries:
        return False

    found_change = False

    for entry in entries:
        if not isinstance(entry, dict):
            return False

        changes = entry.get("changes")
        if not isinstance(changes, list) or not changes:
            return False

        for change in changes:
            if not isinstance(change, dict):
                return False

            if change.get("field") != "messages":
                return False

            value = change.get("value")
            if not isinstance(value, dict):
                return False

            found_change = True

    return found_change


def parse_whatsapp_inbound_messages(payload: dict) -> list[dict[str, str]]:
    """Extract inbound text messages from a Meta WhatsApp webhook payload."""
    messages: list[dict[str, str]] = []

    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return messages

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue

            value = change.get("value", {})
            if not isinstance(value, dict):
                continue

            raw_messages = value.get("messages", [])
            if not isinstance(raw_messages, list):
                continue

            for raw_message in raw_messages:
                if not isinstance(raw_message, dict):
                    continue

                text_payload = raw_message.get("text", {})
                if not isinstance(text_payload, dict):
                    continue

                message_id = raw_message.get("id")
                sender = raw_message.get("from")
                body = text_payload.get("body")

                if not all(
                    isinstance(item, str) and item
                    for item in (message_id, sender, body)
                ):
                    continue

                messages.append(
                    {
                        "message_id": message_id,
                        "sender": sender,
                        "text": body,
                    }
                )

    return messages
