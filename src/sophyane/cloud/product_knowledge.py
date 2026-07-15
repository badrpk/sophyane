"""Grounded product answers for Sophyane (no slow LLM required).

Built from the live merchant/payments/messaging config so chat + Telegram
always know how to pay and how to contact Sophyane.
"""

from __future__ import annotations

import re
from typing import Any


def _match(text: str, *needles: str) -> bool:
    t = text.lower()
    return any(n in t for n in needles)


def product_answer(message: str) -> str | None:
    """Return a concise grounded answer, or None if not a product question."""
    msg = (message or "").strip()
    if not msg:
        return None
    low = msg.lower()

    # --- Identity / what is Sophyane ---
    if _match(low, "what is sophyane", "who is sophyane", "about sophyane", "sophyane kya"):
        return (
            "**Sophyane** is a multi-channel AI agent platform (cloud + local models).\n"
            "Users chat via **web**, **Telegram @sophyanebot**, and get alerts on "
            "**email** + **WhatsApp**.\n"
            "Merchant: Badar Uzaman · badrpk@gmail.com · +92 321 2558089."
        )

    # --- Payment methods ---
    if _match(
        low,
        "how to pay",
        "how can i pay",
        "payment method",
        "payment options",
        "pay for",
        "billing",
        "upgrade plan",
        "how do users pay",
        "accept payment",
        "easypaisa",
        "jazzcash",
        "upaisa",
        "monero",
        "stripe",
        "crypto pay",
        "kucoin",
        "coinbase",
        "binance",
    ):
        return payment_methods_answer()

    # --- Channels / contact ---
    if _match(
        low,
        "how to contact",
        "whatsapp",
        "telegram",
        "channels",
        "communicate",
        "support",
        "contact sophyane",
        "reach you",
    ):
        return channels_answer()

    # --- Plans / pricing ---
    if _match(low, "plan", "pricing", "price", "cost", "subscription", "free tier"):
        return plans_answer()

    # --- OTP / login ---
    if _match(low, "login", "sign up", "signup", "otp", "api key", "how to register"):
        return (
            "**Login / signup**\n"
            "1. Open Sophyane cloud browser → email OTP (from badrpk@gmail.com).\n"
            "2. Enter the 6-digit code → get API key.\n"
            "3. Optional: Telegram `/link you@email.com` on @sophyanebot to link chat.\n"
            "Chat also works on web (API) and Telegram without paying."
        )

    return None


def payment_methods_answer() -> str:
    ready: list[str] = []
    setup: list[str] = []
    try:
        from sophyane.cloud.payments_rails import public_config

        cfg = public_config()
        for m in cfg.get("methods") or []:
            name = m.get("name") or m.get("id")
            if m.get("needs_setup"):
                setup.append(f"· {name} (needs deposit address in config)")
            else:
                extra = m.get("pay_to_preview") or m.get("address_preview") or m.get("pay_to") or ""
                ready.append(f"· **{name}**" + (f" → `{extra}`" if extra else ""))
        merchant = cfg.get("merchant") or {}
    except Exception:
        merchant = {"phone_local": "03212558089", "email": "badrpk@gmail.com"}
        ready = [
            "· **Monero (XMR)**",
            "· **JazzCash / EasyPaisa / UPaisa** (PKR)",
            "· **Stripe card**",
        ]
        setup = ["· KuCoin / Coinbase / Binance (add deposit addresses)"]

    # Stripe
    try:
        from sophyane.cloud.stripe_billing import public_config as stripe_public

        if stripe_public().get("enabled"):
            ready.insert(0, "· **Card (Stripe Checkout)** — live, GBP")
    except Exception:
        ready.insert(0, "· **Card (Stripe)** — when configured")

    phone = merchant.get("phone_local") or "03212558089"
    email = merchant.get("email") or "badrpk@gmail.com"
    lines = [
        "**How to pay for Sophyane plans**",
        "",
        "**Ready now:**",
        *ready,
        "",
        "Open the cloud app → **Upgrade** → choose Card or Crypto/PK wallets.",
        f"Pakistan mobile wallets pay to **{phone}** (Badar Uzaman).",
        "After transfer, enter TID/TXID → plan activates.",
    ]
    if setup:
        lines += ["", "**Pending merchant setup:**", *setup]
    lines += [
        "",
        f"Support: Telegram @sophyanebot · WhatsApp · {email}",
    ]
    return "\n".join(lines)


def channels_answer() -> str:
    bot = "sophyanebot"
    try:
        from sophyane.cloud.messaging import load_messaging_env

        bot = load_messaging_env().get("TELEGRAM_BOT_USERNAME") or bot
    except Exception:
        pass
    return (
        "**Sophyane user channels (all live)**\n"
        f"1. **Telegram** — @{bot} (chat, /pay, /link, alerts)\n"
        "2. **Email** — OTP + notifications from badrpk@gmail.com\n"
        "3. **WhatsApp** — alerts & support on +92 321 2558089\n"
        "4. **Web app** — full UI + API chat\n\n"
        "Message the bot freely; payment and system events notify on all three."
    )


def plans_answer() -> str:
    try:
        from sophyane.cloud.pricing import list_plans

        plans = list_plans()
    except Exception:
        plans = []
    if not plans:
        return (
            "Plans: Free, Hybrid (edge), Builder (~$1/mo), Scale (~$9/mo). "
            "See Upgrade in the cloud app."
        )
    lines = ["**Sophyane plans**", ""]
    for p in plans:
        price = p.get("price_usd_month")
        price_s = "free" if not price else f"${price}/mo"
        lines.append(f"· **{p.get('name') or p.get('id')}** — {price_s}: {p.get('description') or ''}")
    lines.append("")
    lines.append("Upgrade in the cloud browser, or ask Telegram /pay.")
    return "\n".join(lines)


def inject_system_context() -> str:
    """Short system blurb for LLM prompts."""
    return (
        "You are Sophyane. Prefer live product facts: "
        "payments = Stripe card, Monero, JazzCash/EasyPaisa/UPaisa on 03212558089, "
        "optional KuCoin/Coinbase/Binance when addresses set. "
        "User channels = Telegram @sophyanebot, email badrpk@gmail.com, WhatsApp +923212558089. "
        "Do not invent other payment rails. Be concise."
    )
