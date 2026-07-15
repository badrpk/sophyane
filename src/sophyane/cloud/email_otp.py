"""Send one-time passcodes via Gmail SMTP (badrpk@gmail.com)."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

ENV_FILE = Path.home() / ".shmry_email.env"


def load_smtp_env(path: Path | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    p = path or ENV_FILE
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"):
        if os.environ.get(k):
            env[k] = os.environ[k].strip()
    return env


def send_otp_email(to_email: str, otp: str, *, purpose: str = "signup") -> dict[str, Any]:
    """Send a 6-digit OTP from the configured Gmail account (badrpk)."""
    env = load_smtp_env()
    host = env.get("SMTP_HOST", "smtp.gmail.com")
    port = int(env.get("SMTP_PORT") or "587")
    user = env.get("SMTP_USER") or ""
    password = (env.get("SMTP_PASS") or "").replace(" ", "")
    from_addr = env.get("SMTP_FROM") or user
    if not user or not password or "your_email" in user:
        return {
            "ok": False,
            "error": "SMTP not configured. Set ~/.shmry_email.env with SMTP_USER/SMTP_PASS (Gmail app password).",
        }

    action = "sign up for" if purpose == "signup" else "log in to"
    msg = EmailMessage()
    msg["Subject"] = f"Sophyane verification code: {otp}"
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(
        f"""Hello,

Your Sophyane Cloud one-time code to {action} your account is:

    {otp}

This code expires in 10 minutes. Do not share it.

If you did not request this, ignore this email.

— Sophyane (sent via {from_addr})
"""
    )
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=45) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True, "to": to_email, "from": from_addr, "purpose": purpose}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error)}
