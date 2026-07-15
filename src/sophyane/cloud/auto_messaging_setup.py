"""Auto-wire Sophyane messaging after user provides keys or WA links.

Run: python -m sophyane.cloud.auto_messaging_setup
Or:  python auto_messaging_setup.py --telegram-token TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

from sophyane.cloud.messaging import (
    MESSAGING_ENV,
    discover_telegram_chat,
    notify_owner,
    public_status,
    send_email,
    send_telegram,
    send_whatsapp,
    telegram_get_me,
    _upsert_messaging_env,
)

WA_STATUS = Path.home() / ".local/share/sophyane/messaging-bridge/state/status.json"
WA_SEND = Path.home() / ".local/share/sophyane/messaging-bridge/wa_send.sh"


def wire_whatsapp_cmd() -> None:
    cmd = f"{WA_SEND} {{to}} {{msg}}"
    _upsert_messaging_env("WHATSAPP_SEND_CMD", cmd)
    _upsert_messaging_env("WHATSAPP_OWNER", "923212558089")
    _upsert_messaging_env("MERCHANT_WHATSAPP", "923212558089")
    _upsert_messaging_env("MERCHANT_PHONE", "+923212558089")
    _upsert_messaging_env("MERCHANT_EMAIL", "badrpk@gmail.com")


def wait_wa_ready(timeout: int = 300) -> dict:
    """Poll bridge until linked or timeout."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8791/status", timeout=3) as r:
                last = json.loads(r.read().decode())
            if last.get("ready"):
                return {"ok": True, **last}
        except Exception as e:
            last = {"ok": False, "error": str(e)}
        time.sleep(2)
    return {"ok": False, "timeout": True, **last}


def apply_telegram_token(token: str) -> dict:
    token = token.strip()
    if not token or ":" not in token:
        return {"ok": False, "error": "invalid token format (expect 123456:ABC...)"}
    _upsert_messaging_env("TELEGRAM_BOT_TOKEN", token)
    me = telegram_get_me()
    if not me.get("ok"):
        return {"ok": False, "error": "token rejected by Telegram", "detail": me}
    bot = me.get("bot") or {}
    if bot.get("username"):
        _upsert_messaging_env("TELEGRAM_BOT_USERNAME", bot["username"])
    disc = discover_telegram_chat()
    test = None
    if disc.get("ok"):
        test = send_telegram(
            "✅ Sophyane Telegram linked.\n"
            "Merchant: badrpk@gmail.com · +923212558089\n"
            "Bot is ready for payment alerts and commands."
        )
    return {
        "ok": True,
        "bot": bot,
        "discover": disc,
        "test_message": test,
        "hint": None
        if disc.get("ok")
        else "Open Telegram, message your bot /start, then re-run discover.",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--telegram-token", default=os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    p.add_argument("--wait-wa", type=int, default=0, help="seconds to wait for WA QR link")
    p.add_argument("--notify", action="store_true")
    args = p.parse_args(argv)

    wire_whatsapp_cmd()
    results: dict = {"whatsapp_cmd": str(WA_SEND), "status": public_status()}

    if args.telegram_token:
        results["telegram"] = apply_telegram_token(args.telegram_token)

    if args.wait_wa > 0:
        results["whatsapp_wait"] = wait_wa_ready(args.wait_wa)

    if args.notify:
        results["notify"] = notify_owner(
            "Sophyane auto-setup complete.\n" + json.dumps(public_status(), indent=2)[:1500],
            channels=["email", "telegram", "whatsapp"],
        )

    print(json.dumps(results, indent=2, default=str))
    return 0 if results.get("telegram", {}).get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
