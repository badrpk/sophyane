"""Sophyane Telegram bot — full user communication channel.

Any user can message @sophyanebot for chat/agent help.
Links Telegram chat_id ↔ Sophyane user (email) for personalized plan/API.
Outbound: payment alerts, OTP notices, system messages on Telegram + email + WhatsApp.

Poller: python -m sophyane.cloud.telegram_bot
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from sophyane.cloud.messaging import (
    _tg_api,
    load_messaging_env,
    merchant_contacts,
    send_email,
    send_telegram,
    send_whatsapp,
)

DB_PATH = Path.home() / ".local" / "state" / "sophyane" / "cloud" / "channel_links.db"
OFFSET_PATH = Path.home() / ".local" / "state" / "sophyane" / "telegram_offset.json"
LOG_PATH = Path.home() / ".local" / "state" / "sophyane" / "telegram_bot.log"


def _log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(msg, flush=True)


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS telegram_users (
          chat_id TEXT PRIMARY KEY,
          username TEXT,
          first_name TEXT,
          user_id TEXT,
          email TEXT,
          created_at REAL NOT NULL,
          last_seen REAL NOT NULL,
          notes TEXT
        );
        CREATE TABLE IF NOT EXISTS channel_links (
          id TEXT PRIMARY KEY,
          user_id TEXT,
          email TEXT,
          channel TEXT NOT NULL,
          address TEXT NOT NULL,
          verified INTEGER NOT NULL DEFAULT 0,
          created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cl_email ON channel_links(email, channel);
        CREATE INDEX IF NOT EXISTS idx_tg_user ON telegram_users(user_id);
        """
    )
    con.commit()
    return con


def upsert_telegram_user(
    chat_id: str | int,
    *,
    username: str = "",
    first_name: str = "",
    user_id: str = "",
    email: str = "",
) -> dict[str, Any]:
    cid = str(chat_id)
    now = time.time()
    with _conn() as con:
        row = con.execute("SELECT * FROM telegram_users WHERE chat_id=?", (cid,)).fetchone()
        if row:
            con.execute(
                """
                UPDATE telegram_users SET username=COALESCE(NULLIF(?,''), username),
                  first_name=COALESCE(NULLIF(?,''), first_name),
                  user_id=COALESCE(NULLIF(?,''), user_id),
                  email=COALESCE(NULLIF(?,''), email),
                  last_seen=?
                WHERE chat_id=?
                """,
                (username, first_name, user_id, email.lower() if email else "", now, cid),
            )
        else:
            con.execute(
                """
                INSERT INTO telegram_users(chat_id, username, first_name, user_id, email, created_at, last_seen)
                VALUES (?,?,?,?,?,?,?)
                """,
                (cid, username, first_name, user_id, email.lower() if email else "", now, now),
            )
        con.commit()
        row = con.execute("SELECT * FROM telegram_users WHERE chat_id=?", (cid,)).fetchone()
    return dict(row) if row else {"chat_id": cid}


def get_telegram_user(chat_id: str | int) -> dict[str, Any] | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM telegram_users WHERE chat_id=?", (str(chat_id),)).fetchone()
    return dict(row) if row else None


def link_email_to_chat(chat_id: str | int, email: str) -> dict[str, Any]:
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"ok": False, "error": "invalid email"}
    from sophyane.cloud.store import PortalStore

    store = PortalStore()
    user = store.get_user_by_email(email)
    uid = user["id"] if user else ""
    rec = upsert_telegram_user(chat_id, email=email, user_id=uid)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO channel_links(id, user_id, email, channel, address, verified, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"tg_{chat_id}_{int(time.time())}",
                uid,
                email,
                "telegram",
                str(chat_id),
                1,
                time.time(),
            ),
        )
        con.commit()
    return {"ok": True, "user": user, "telegram": rec, "linked": bool(user)}


def chats_for_email(email: str) -> list[str]:
    email = email.strip().lower()
    with _conn() as con:
        rows = con.execute(
            "SELECT chat_id FROM telegram_users WHERE email=? ORDER BY last_seen DESC",
            (email,),
        ).fetchall()
        rows2 = con.execute(
            "SELECT address FROM channel_links WHERE email=? AND channel='telegram' AND verified=1",
            (email,),
        ).fetchall()
    ids = [str(r[0]) for r in rows] + [str(r[0]) for r in rows2]
    return list(dict.fromkeys(ids))


def tg_send(chat_id: str | int, text: str) -> dict[str, Any]:
    try:
        data = _tg_api(
            "sendMessage",
            {"chat_id": str(chat_id), "text": text[:4000], "disable_web_page_preview": True},
        )
        if data.get("ok"):
            return {"ok": True, "channel": "telegram", "chat_id": str(chat_id), "message_id": (data.get("result") or {}).get("message_id")}
        return {"ok": False, "error": str(data), "channel": "telegram"}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err), "channel": "telegram"}


def notify_user(
    *,
    email: str = "",
    telegram_chat_id: str = "",
    phone: str = "",
    text: str,
    channels: list[str] | None = None,
    subject: str = "Sophyane notification",
) -> dict[str, Any]:
    """Send to a user on telegram + email + whatsapp (all available)."""
    want = channels or ["telegram", "email", "whatsapp"]
    results: dict[str, Any] = {}
    m = merchant_contacts()

    if "telegram" in want:
        chats: list[str] = []
        if telegram_chat_id:
            chats.append(str(telegram_chat_id))
        if email:
            chats.extend(chats_for_email(email))
        # owner fallback if email matches merchant
        if email and email.lower() == m["email"].lower() and m.get("telegram_chat_id"):
            chats.append(str(m["telegram_chat_id"]))
        chats = list(dict.fromkeys([c for c in chats if c]))
        tg_results = []
        for cid in chats:
            tg_results.append(tg_send(cid, text))
        if not chats and m.get("telegram_chat_id") and not email:
            tg_results.append(tg_send(m["telegram_chat_id"], text))
        results["telegram"] = tg_results if tg_results else {"ok": False, "error": "no telegram chat for user"}

    if "email" in want and email:
        results["email"] = send_email(email, subject, text)
    elif "email" in want and not email:
        results["email"] = {"ok": False, "error": "no email"}

    if "whatsapp" in want:
        to = phone or (m["whatsapp"] if (not email or email.lower() == m["email"].lower()) else "")
        if to:
            results["whatsapp"] = send_whatsapp(to, text)
        else:
            results["whatsapp"] = {"ok": False, "error": "no whatsapp number"}

    ok_any = False
    for v in results.values():
        if isinstance(v, dict) and v.get("ok"):
            ok_any = True
        if isinstance(v, list) and any(x.get("ok") for x in v if isinstance(x, dict)):
            ok_any = True
    return {"ok": ok_any, "results": results}


def notify_all_channels(text: str, *, subject: str = "Sophyane") -> dict[str, Any]:
    """Notify merchant owner on every live channel."""
    m = merchant_contacts()
    return notify_user(
        email=m["email"],
        telegram_chat_id=m.get("telegram_chat_id") or "",
        phone=m["whatsapp"],
        text=text,
        subject=subject,
        channels=["telegram", "email", "whatsapp"],
    )


def _chat_reply(message: str, *, email: str = "", plan: str = "free") -> str:
    """Generate assistant reply (shared with portal intelligence)."""
    message = (message or "").strip()
    if not message:
        return "Send a message, or /help for commands."

    # Trivial math
    trivial = re.search(
        r"(?:what\s+is|calculate|compute)?\s*(\d+)\s*([+\-*/x×])\s*(\d+)",
        message.lower(),
    )
    if trivial:
        a, op, b = int(trivial.group(1)), trivial.group(2), int(trivial.group(3))
        ops = {"+": a + b, "-": a - b, "*": a * b, "x": a * b, "×": a * b, "/": (a / b if b else "undefined")}
        val = ops.get(op)
        if val is not None:
            return str(int(val) if isinstance(val, float) and val == int(val) else val)

    # Prefer web-grounded when possible
    try:
        from sophyane.web_intel import (
            format_search_context,
            grounded_answer_from_search,
            needs_web_research,
            web_search,
        )

        if needs_web_research(message):
            hits = web_search(message, max_results=5)
            if hits:
                grounded = grounded_answer_from_search(message, hits)
                if grounded:
                    return grounded[:3500]
                ctx = format_search_context(hits)
                return (ctx[:3000] + "\n\n(Ask a follow-up for more detail.)") if ctx else "No web results."
    except Exception as err:  # noqa: BLE001
        _log(f"web_intel: {err}")

    try:
        from sophyane.config import load_config
        from sophyane.main import create_provider

        cfg = load_config()
        provider = create_provider(cfg)
        system = (
            "You are Sophyane, a helpful AI assistant on Telegram. "
            "Be concise and useful. Merchant channels: email, WhatsApp, Telegram. "
            f"User plan: {plan or 'free'}. Email: {email or 'guest'}."
        )
        out = provider.generate(message, system)
        return (out or "").strip()[:3500] or "I could not generate a reply. Try again."
    except Exception as err:  # noqa: BLE001
        _log(f"llm: {err}")
        return (
            "Sophyane Telegram is online. "
            "I could not reach a cloud model just now. "
            "Try again, or open the cloud browser chat. "
            f"({type(err).__name__})"
        )


HELP = """Sophyane Telegram bot

Commands:
/start — welcome + link status
/help — this help
/status — your link + plan
/link you@email.com — link this chat to your Sophyane account
/pay — payment options (Stripe, crypto, JazzCash/EasyPaisa)
/channels — how Sophyane reaches you

Or just send any question — I'll answer here.

Also available: email (badrpk@gmail.com) · WhatsApp · web app
"""


def handle_command(chat_id: str, text: str, user_row: dict[str, Any]) -> str:
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in {"/start", "/hello"}:
        m = merchant_contacts()
        linked = user_row.get("email") or ""
        return (
            "Welcome to Sophyane 🤖\n\n"
            "I am your multi-channel AI assistant.\n"
            f"Bot: @{(load_messaging_env().get('TELEGRAM_BOT_USERNAME') or 'sophyanebot')}\n"
            f"Linked email: {linked or '(not linked — /link you@email.com)'}\n\n"
            "Send any message to chat.\n"
            f"/help · /pay · /status\n\n"
            f"Merchant: {m['name']} · {m['email']} · {m['phone']}"
        )

    if cmd == "/help":
        return HELP

    if cmd == "/status":
        plan = "guest"
        if user_row.get("email"):
            try:
                from sophyane.cloud.store import PortalStore

                u = PortalStore().get_user_by_email(user_row["email"])
                plan = (u or {}).get("plan") or "free"
            except Exception:
                plan = "free"
        return (
            f"Telegram chat: {chat_id}\n"
            f"Username: @{user_row.get('username') or '—'}\n"
            f"Email: {user_row.get('email') or 'not linked'}\n"
            f"Plan: {plan}\n"
            f"Channels: Telegram ✅ · Email ✅ · WhatsApp ✅"
        )

    if cmd == "/link":
        if not arg:
            return "Usage: /link your@email.com\nThen use email OTP on the web app if you need an API key."
        res = link_email_to_chat(chat_id, arg)
        if not res.get("ok"):
            return f"Link failed: {res.get('error')}"
        if res.get("linked"):
            return f"Linked this Telegram chat to Sophyane account {arg}. Plan: {(res.get('user') or {}).get('plan')}"
        return (
            f"Saved email {arg} on this chat. "
            "No cloud account yet — sign up at the Sophyane web app with that email (OTP), "
            "then message me again."
        )

    if cmd == "/pay":
        m = merchant_contacts()
        return (
            "Sophyane payment options:\n"
            "• Card — Stripe (Monzo-linked)\n"
            "• Monero (XMR) — local wallet invoices\n"
            "• JazzCash / EasyPaisa / UPaisa — PKR to "
            f"{m['phone_local']}\n"
            "• KuCoin / Coinbase / Binance — when deposit addresses set\n\n"
            "Open Upgrade in the Sophyane cloud browser, or ask me for a plan quote."
        )

    if cmd == "/channels":
        return (
            "Sophyane reaches users on:\n"
            "1. Telegram — this bot (@sophyanebot)\n"
            "2. Email — OTP + notifications from badrpk@gmail.com\n"
            "3. WhatsApp — linked device bridge\n\n"
            "Admins can broadcast alerts on all three."
        )

    return ""


def process_update(update: dict[str, Any]) -> dict[str, Any]:
    msg = update.get("message") or update.get("edited_message") or {}
    if not msg:
        return {"ok": False, "skip": True}
    chat = msg.get("chat") or {}
    if chat.get("type") not in {"private", "group", "supergroup"}:
        return {"ok": False, "skip": True, "reason": "chat type"}
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return {"ok": False, "error": "no chat_id"}
    from_user = msg.get("from") or {}
    text = (msg.get("text") or msg.get("caption") or "").strip()
    user_row = upsert_telegram_user(
        chat_id,
        username=str(from_user.get("username") or chat.get("username") or ""),
        first_name=str(from_user.get("first_name") or chat.get("first_name") or ""),
    )

    if not text:
        tg_send(chat_id, "Send text, or /help.")
        return {"ok": True, "kind": "empty"}

    if text.startswith("/"):
        reply = handle_command(chat_id, text, user_row)
        if reply:
            tg_send(chat_id, reply)
            return {"ok": True, "kind": "command", "cmd": text.split()[0]}

    # Refresh row after possible /link in same message handled above
    user_row = get_telegram_user(chat_id) or user_row
    email = user_row.get("email") or ""
    plan = "guest"
    if email:
        try:
            from sophyane.cloud.store import PortalStore

            u = PortalStore().get_user_by_email(email)
            if u:
                plan = u.get("plan") or "free"
        except Exception:
            pass

    # Typing indicator optional — skip for reliability
    reply = _chat_reply(text, email=email, plan=plan)
    sent = tg_send(chat_id, reply)
    return {"ok": True, "kind": "chat", "sent": sent}


def load_offset() -> int:
    if OFFSET_PATH.exists():
        try:
            return int(json.loads(OFFSET_PATH.read_text()).get("offset") or 0)
        except Exception:
            return 0
    return 0


def save_offset(offset: int) -> None:
    OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_PATH.write_text(json.dumps({"offset": offset, "ts": time.time()}), encoding="utf-8")


def poll_once(offset: int = 0) -> tuple[int, list[dict[str, Any]]]:
    params: dict[str, Any] = {
        "timeout": 25,
        "limit": 50,
        "allowed_updates": ["message", "edited_message"],
    }
    if offset:
        params["offset"] = offset
    data = _tg_api("getUpdates", params)
    if not data.get("ok"):
        raise RuntimeError(str(data))
    results = data.get("result") or []
    new_offset = offset
    out = []
    for upd in results:
        uid = int(upd.get("update_id") or 0)
        if uid >= new_offset:
            new_offset = uid + 1
        try:
            out.append(process_update(upd))
        except Exception as err:  # noqa: BLE001
            _log(f"process_update error: {err}")
            out.append({"ok": False, "error": str(err)})
    return new_offset, out


def run_poller(loop: bool = True) -> None:
    env = load_messaging_env()
    if not (env.get("TELEGRAM_BOT_TOKEN") or "").strip():
        raise SystemExit("TELEGRAM_BOT_TOKEN not set")
    # Ensure webhook deleted so getUpdates works
    try:
        _tg_api("deleteWebhook", {"drop_pending_updates": False})
    except Exception as err:
        _log(f"deleteWebhook: {err}")
    me = _tg_api("getMe")
    _log(f"bot online: {(me.get('result') or {}).get('username')}")
    # greet owner once if configured
    m = merchant_contacts()
    if m.get("telegram_chat_id"):
        tg_send(
            m["telegram_chat_id"],
            "Sophyane Telegram worker started.\n"
            "Users can message this bot for chat + support.\n"
            "Channels: Telegram · Email · WhatsApp",
        )
    offset = load_offset()
    while True:
        try:
            offset, outs = poll_once(offset)
            if outs:
                save_offset(offset)
                _log(f"processed {len(outs)} updates offset={offset}")
            else:
                save_offset(offset)
        except Exception as err:  # noqa: BLE001
            _log(f"poll error: {err}")
            time.sleep(3)
        if not loop:
            break


def main() -> None:
    run_poller(loop=True)


if __name__ == "__main__":
    main()
