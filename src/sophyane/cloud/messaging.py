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

MESSAGING_ENV = Path.home() / ".config" / "sophyane" / "messaging.env"
PAYMENTS_ENV = Path.home() / ".config" / "sophyane" / "payments.env"
SMTP_ENV = Path.home() / ".shmry_email.env"
WA_OUTBOX = Path.home() / ".local" / "state" / "sophyane" / "whatsapp_outbox" / "queue.jsonl"
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
    smtp_ok = bool((e.get("SMTP_USER") or "").strip() and (e.get("SMTP_PASS") or "").strip())
    channels = {
        "email": {"enabled": smtp_ok, "from": e.get("SMTP_USER") or m["email"], "status": "live" if smtp_ok else "needs_smtp"},
        "telegram": {
            "enabled": tg_token,
            "bot_username": e.get("TELEGRAM_BOT_USERNAME") or "",
            "owner_chat_id": m["telegram_chat_id"],
            "status": "live" if tg_token else "needs_bot_token",
            "hint": "Message @BotFather → /newbot → put token in messaging.env TELEGRAM_BOT_TOKEN",
        },
        "whatsapp": {
            "enabled": wa_cloud or wa_cmd,
            "owner": m["whatsapp"],
            "mode": "cloud_api" if wa_cloud else ("local_cmd" if wa_cmd else "outbox_only"),
            "status": "live" if (wa_cloud or wa_cmd) else "needs_bridge",
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
    e = load_messaging_env()
    token = (e.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in messaging.env")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "SophyaneBot/17.3"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def telegram_get_me() -> dict[str, Any]:
    try:
        data = _tg_api("getMe")
        if data.get("ok"):
            result = data.get("result") or {}
            # cache username
            e = load_messaging_env()
            if result.get("username") and MESSAGING_ENV.exists():
                pass
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
