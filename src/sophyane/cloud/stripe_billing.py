"""Stripe Checkout billing for Sophyane paid plans (Monzo-linked live account).

Keys load from ~/.config/sophyane/stripe.env (chmod 600). Never log full secrets.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from sophyane.cloud.pricing import PLANS

STRIPE_ENV = Path.home() / ".config" / "sophyane" / "stripe.env"
API = "https://api.stripe.com/v1"


def load_stripe_env() -> dict[str, str]:
    env: dict[str, str] = {}
    # process env first
    for k in (
        "STRIPE_SECRET_KEY",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_CURRENCY",
        "STRIPE_SUCCESS_PATH",
        "STRIPE_CANCEL_PATH",
    ):
        if os.environ.get(k):
            env[k] = os.environ[k].strip()
    if STRIPE_ENV.exists():
        for line in STRIPE_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def stripe_configured() -> bool:
    env = load_stripe_env()
    sk = env.get("STRIPE_SECRET_KEY", "")
    pk = env.get("STRIPE_PUBLISHABLE_KEY", "")
    return bool(sk.startswith("sk_") and pk.startswith("pk_"))


def public_config() -> dict[str, Any]:
    env = load_stripe_env()
    pk = env.get("STRIPE_PUBLISHABLE_KEY", "")
    mode = "live" if "live" in pk else ("test" if "test" in pk else "unknown")
    return {
        "ok": True,
        "enabled": stripe_configured(),
        "publishable_key": pk,
        "mode": mode,
        "currency": (env.get("STRIPE_CURRENCY") or "gbp").lower(),
        "paid_plans": [
            {"id": pid, **meta}
            for pid, meta in PLANS.items()
            if float(meta.get("price_usd_month") or 0) > 0
        ],
        "note": "Paid plans use Stripe Checkout. Free/hybrid remain free (no card).",
    }


def _stripe_request(path: str, data: dict[str, Any] | None = None, method: str = "POST") -> dict[str, Any]:
    env = load_stripe_env()
    sk = env.get("STRIPE_SECRET_KEY") or ""
    if not sk:
        raise RuntimeError("Stripe secret key not configured")
    body = None
    headers = {"Authorization": f"Bearer {sk}"}
    if data is not None:
        # Stripe expects application/x-www-form-urlencoded
        body = urllib.parse.urlencode(_flatten(data), doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(API + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        err_body = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body)
            msg = parsed.get("error", {}).get("message") or err_body
        except Exception:
            msg = err_body
        raise RuntimeError(f"Stripe API error: {msg}") from error


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            items.extend(_flatten(v, key))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    items.extend(_flatten(item, f"{key}[{i}]"))
                else:
                    items.append((f"{key}[{i}]", str(item)))
        elif v is None:
            continue
        else:
            items.append((key, str(v)))
    return items


def create_checkout_session(
    *,
    plan_id: str,
    user_id: str,
    email: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    plan = PLANS.get(plan_id)
    if not plan:
        return {"ok": False, "error": f"unknown plan {plan_id}"}
    price = float(plan.get("price_usd_month") or 0)
    if price <= 0:
        return {"ok": False, "error": "plan is free — no checkout needed", "free": True}

    env = load_stripe_env()
    currency = (env.get("STRIPE_CURRENCY") or "gbp").lower()
    # Charge monthly subscription-style one-time first invoice via recurring
    # Use subscription mode for monthly plans
    unit_amount = int(round(price * 100))  # price_usd_month treated as major units
    # Note: account currency is GBP; keep amounts as listed (1 / 9) in account currency.
    payload = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": user_id,
        "customer_email": email,
        "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": currency,
        "line_items[0][price_data][unit_amount]": unit_amount,
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][price_data][product_data][name]": f"Sophyane {plan.get('name')} plan",
        "line_items[0][price_data][product_data][description]": str(plan.get("description") or "")[:500],
        "metadata[plan]": plan_id,
        "metadata[user_id]": user_id,
        "metadata[email]": email,
        "subscription_data[metadata][plan]": plan_id,
        "subscription_data[metadata][user_id]": user_id,
        "allow_promotion_codes": "true",
    }
    session = _stripe_request("/checkout/sessions", payload)
    return {
        "ok": True,
        "session_id": session.get("id"),
        "url": session.get("url"),
        "plan": plan_id,
        "amount": unit_amount,
        "currency": currency,
        "mode": session.get("mode"),
    }


def retrieve_session(session_id: str) -> dict[str, Any]:
    session = _stripe_request(f"/checkout/sessions/{session_id}", method="GET")
    return session


def confirm_session(session_id: str, expected_user_id: str) -> dict[str, Any]:
    """After Checkout redirect: verify paid and return plan to apply."""
    session = retrieve_session(session_id)
    meta = session.get("metadata") or {}
    if str(meta.get("user_id") or "") != str(expected_user_id):
        return {"ok": False, "error": "session does not belong to this user"}
    status = session.get("status") or session.get("payment_status")
    paid = session.get("payment_status") == "paid" or session.get("status") == "complete"
    plan = str(meta.get("plan") or "")
    if not paid:
        return {
            "ok": False,
            "error": f"payment not complete (status={status}, payment_status={session.get('payment_status')})",
            "session": {"id": session.get("id"), "status": session.get("status")},
        }
    if plan not in PLANS:
        return {"ok": False, "error": f"invalid plan on session: {plan}"}
    return {
        "ok": True,
        "plan": plan,
        "session_id": session.get("id"),
        "customer_email": session.get("customer_details", {}).get("email") or session.get("customer_email"),
        "amount_total": session.get("amount_total"),
        "currency": session.get("currency"),
    }
