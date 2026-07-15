"""Multi-rail payments for Sophyane Cloud.

Rails:
  - Crypto: Monero + KuCoin (via crypto_billing)
  - Exchanges: Coinbase + Binance deposit addresses / optional API
  - Pakistan mobile money: JazzCash, EasyPaisa, UPaisa (MSISDN receive)

Merchant identity (default):
  email: badrpk@gmail.com
  phone: +923212558089

Receive: create invoice → user pays → user reports txid/reference → plan activate.
Disburse: record outbound payout request (operator / API when keys present).

Secrets live only in ~/.config/sophyane/{crypto,payments,stripe}.env — never commit.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from sophyane.cloud.pricing import PLANS

PAYMENTS_ENV = Path.home() / ".config" / "sophyane" / "payments.env"
CRYPTO_ENV = Path.home() / ".config" / "sophyane" / "crypto.env"
DB_PATH = Path.home() / ".local" / "state" / "sophyane" / "cloud" / "payments_rails.db"

DEFAULT_EMAIL = "badrpk@gmail.com"
DEFAULT_PHONE = "+923212558089"
DEFAULT_PHONE_LOCAL = "03212558089"


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_payments_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith(
            (
                "PAY_",
                "MERCHANT_",
                "COINBASE_",
                "BINANCE_",
                "JAZZCASH_",
                "EASYPAISA_",
                "UPAISA_",
                "CRYPTO_",
                "MONERO_",
                "KUCOIN_",
            )
        ):
            env[k] = v.strip()
    env.update(_parse_env_file(CRYPTO_ENV))
    env.update(_parse_env_file(PAYMENTS_ENV))
    return env


def merchant_identity(env: dict[str, str] | None = None) -> dict[str, str]:
    e = env or load_payments_env()
    email = e.get("MERCHANT_EMAIL") or e.get("CRYPTO_OWNER_EMAIL") or DEFAULT_EMAIL
    phone = e.get("MERCHANT_PHONE") or DEFAULT_PHONE
    phone_local = e.get("MERCHANT_PHONE_LOCAL") or DEFAULT_PHONE_LOCAL
    name = e.get("MERCHANT_NAME") or "Badar Uzaman"
    return {
        "email": email,
        "phone": phone,
        "phone_local": phone_local,
        "name": name,
        "whatsapp": phone.replace("+", "").replace(" ", ""),
    }


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS rail_invoices (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          email TEXT,
          plan TEXT NOT NULL,
          rail TEXT NOT NULL,
          method TEXT NOT NULL,
          asset TEXT,
          network TEXT,
          currency TEXT NOT NULL,
          amount REAL NOT NULL,
          amount_str TEXT NOT NULL,
          pay_to TEXT NOT NULL,
          pay_to_label TEXT,
          status TEXT NOT NULL,
          reference TEXT,
          txid TEXT,
          created_at REAL NOT NULL,
          expires_at REAL NOT NULL,
          paid_at REAL,
          note TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS rail_payouts (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          rail TEXT NOT NULL,
          method TEXT NOT NULL,
          amount REAL NOT NULL,
          currency TEXT NOT NULL,
          destination TEXT NOT NULL,
          status TEXT NOT NULL,
          reference TEXT,
          created_at REAL NOT NULL,
          completed_at REAL,
          note TEXT
        )
        """
    )
    con.commit()
    return con


def _http_json(url: str, timeout: float = 12.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "SophyanePay/17.3", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_usd_pkr_rate() -> float:
    try:
        data = _http_json("https://api.exchangerate.host/latest?base=USD&symbols=PKR")
        rate = float((data.get("rates") or {}).get("PKR") or 0)
        if rate > 0:
            return rate
    except Exception:
        pass
    try:
        data = _http_json("https://open.er-api.com/v6/latest/USD")
        rate = float((data.get("rates") or {}).get("PKR") or 0)
        if rate > 0:
            return rate
    except Exception:
        pass
    return 278.0  # fallback approx


def plan_price_usd(plan_id: str) -> float:
    plan = PLANS.get(plan_id) or {}
    return float(plan.get("price_usd_month") or 0)


def _ttl_min(env: dict[str, str]) -> int:
    return int(env.get("PAY_INVOICE_TTL_MIN") or env.get("CRYPTO_INVOICE_TTL_MIN") or 90)


# ── Rail catalogue ──────────────────────────────────────────────────────────


def list_receive_methods() -> list[dict[str, Any]]:
    """Public list of receive rails (no secrets)."""
    env = load_payments_env()
    m = merchant_identity(env)
    methods: list[dict[str, Any]] = []

    # Monero / KuCoin via crypto_billing when available
    try:
        from sophyane.cloud.crypto_billing import public_config as crypto_public

        c = crypto_public()
        for item in c.get("methods") or []:
            if item.get("needs_setup"):
                methods.append(
                    {
                        "id": item.get("id") or "kucoin_setup",
                        "rail": "crypto",
                        "name": item.get("name"),
                        "needs_setup": True,
                        "hint": item.get("hint"),
                        "account": item.get("account") or m["email"],
                    }
                )
            else:
                methods.append(
                    {
                        "id": item["id"],
                        "rail": "crypto",
                        "name": item.get("name"),
                        "asset": item.get("asset"),
                        "address_preview": item.get("address_preview"),
                        "account": m["email"],
                    }
                )
    except Exception:
        methods.append(
            {
                "id": "monero",
                "rail": "crypto",
                "name": "Monero (XMR)",
                "asset": "XMR",
                "account": m["email"],
            }
        )

    # Coinbase
    cb_on = env.get("COINBASE_ENABLED", "1") == "1"
    if cb_on:
        for asset, key in (("BTC", "COINBASE_BTC_ADDRESS"), ("ETH", "COINBASE_ETH_ADDRESS"), ("USDC", "COINBASE_USDC_ADDRESS")):
            addr = (env.get(key) or "").strip()
            if addr:
                methods.append(
                    {
                        "id": f"coinbase_{asset.lower()}",
                        "rail": "coinbase",
                        "name": f"Coinbase {asset}",
                        "asset": asset,
                        "address_preview": addr[:10] + "…" + addr[-6:],
                        "account": env.get("COINBASE_ACCOUNT_EMAIL") or m["email"],
                    }
                )
        if not any(x.get("rail") == "coinbase" and not x.get("needs_setup") for x in methods if x.get("rail") == "coinbase"):
            if not any(x.get("id", "").startswith("coinbase_") and not x.get("needs_setup") for x in methods):
                methods.append(
                    {
                        "id": "coinbase_setup",
                        "rail": "coinbase",
                        "name": "Coinbase (deposit address needed)",
                        "needs_setup": True,
                        "account": env.get("COINBASE_ACCOUNT_EMAIL") or m["email"],
                        "hint": "Add COINBASE_BTC_ADDRESS / ETH / USDC in payments.env, or Coinbase Commerce API key.",
                    }
                )

    # Binance
    bn_on = env.get("BINANCE_ENABLED", "1") == "1"
    if bn_on:
        for asset, key, netkey in (
            ("USDT", "BINANCE_USDT_ADDRESS", "BINANCE_USDT_NETWORK"),
            ("BTC", "BINANCE_BTC_ADDRESS", None),
            ("ETH", "BINANCE_ETH_ADDRESS", None),
        ):
            addr = (env.get(key) or "").strip()
            if addr:
                methods.append(
                    {
                        "id": f"binance_{asset.lower()}",
                        "rail": "binance",
                        "name": f"Binance {asset}",
                        "asset": asset,
                        "network": env.get(netkey or "", "") if netkey else "",
                        "address_preview": addr[:10] + "…" + addr[-6:],
                        "account": env.get("BINANCE_ACCOUNT_EMAIL") or m["email"],
                    }
                )
        if not any(x.get("rail") == "binance" and x.get("address_preview") for x in methods):
            methods.append(
                {
                    "id": "binance_setup",
                    "rail": "binance",
                    "name": "Binance (deposit address needed)",
                    "needs_setup": True,
                    "account": env.get("BINANCE_ACCOUNT_EMAIL") or m["email"],
                    "hint": "Add BINANCE_USDT_ADDRESS (and network) in payments.env from Binance → Deposit.",
                }
            )

    # Pakistan mobile wallets
    for rail, label, en_key, phone_key in (
        ("jazzcash", "JazzCash", "JAZZCASH_ENABLED", "JAZZCASH_PHONE"),
        ("easypaisa", "EasyPaisa", "EASYPAISA_ENABLED", "EASYPAISA_PHONE"),
        ("upaisa", "UPaisa", "UPAISA_ENABLED", "UPAISA_PHONE"),
    ):
        if env.get(en_key, "1") != "1":
            continue
        phone = (env.get(phone_key) or m["phone_local"] or m["phone"]).strip()
        methods.append(
            {
                "id": rail,
                "rail": rail,
                "name": f"{label} (PKR)",
                "asset": "PKR",
                "currency": "PKR",
                "country": "PK",
                "pay_to": phone,
                "pay_to_preview": phone,
                "account_name": env.get(f"{rail.upper()}_ACCOUNT_NAME") or m["name"],
                "account": m["email"],
                "instructions_hint": f"Send PKR to {label} account {phone} ({m['name']}).",
            }
        )

    return methods


def public_config() -> dict[str, Any]:
    env = load_payments_env()
    m = merchant_identity(env)
    methods = list_receive_methods()
    ready = [x for x in methods if not x.get("needs_setup")]
    return {
        "ok": True,
        "enabled": bool(ready),
        "merchant": m,
        "methods": methods,
        "rails": sorted({x.get("rail") for x in methods if x.get("rail")}),
        "receive_ready": [x["id"] for x in ready],
        "disburse_supported": [
            "jazzcash",
            "easypaisa",
            "upaisa",
            "binance",
            "coinbase",
            "monero",
            "kucoin",
        ],
        "note": (
            f"Receive & disburse via multi-rail. Merchant {m['name']} · "
            f"{m['email']} · {m['phone']}. Pakistan: JazzCash/EasyPaisa/UPaisa on MSISDN. "
            "Crypto: Monero/KuCoin/Coinbase/Binance deposit addresses."
        ),
    }


def create_invoice(
    *,
    user_id: str,
    email: str,
    plan_id: str,
    method: str = "easypaisa",
) -> dict[str, Any]:
    plan = PLANS.get(plan_id)
    if not plan:
        return {"ok": False, "error": f"unknown plan {plan_id}"}
    price_usd = plan_price_usd(plan_id)
    if price_usd <= 0:
        return {"ok": False, "error": "plan is free — no payment needed", "free": True}

    env = load_payments_env()
    m = merchant_identity(env)
    method = (method or "").lower().strip()
    ttl = _ttl_min(env)
    now = time.time()
    inv_id = "pay_" + secrets.token_hex(8)

    # Delegate pure crypto methods to crypto_billing
    if method in {"monero", "xmr"} or method.startswith("kucoin"):
        from sophyane.cloud.crypto_billing import create_invoice as crypto_invoice

        return crypto_invoice(user_id=user_id, email=email, plan_id=plan_id, method=method)

    rail = method
    asset = ""
    network = ""
    currency = "USD"
    amount = price_usd
    amount_str = f"{price_usd:.2f}"
    pay_to = ""
    pay_to_label = ""
    instructions = ""

    if method.startswith("coinbase"):
        rail = "coinbase"
        asset = "USDC"
        if "btc" in method:
            asset = "BTC"
        elif "eth" in method:
            asset = "ETH"
        key = f"COINBASE_{asset}_ADDRESS"
        pay_to = (env.get(key) or "").strip()
        if not pay_to:
            return {
                "ok": False,
                "error": (
                    f"Coinbase {asset} address not set for {env.get('COINBASE_ACCOUNT_EMAIL') or m['email']}. "
                    f"Add {key} to ~/.config/sophyane/payments.env"
                ),
            }
        # convert USD to crypto amount roughly via coingecko
        try:
            from sophyane.cloud.crypto_billing import fetch_rates

            rates = fetch_rates()
            rate = rates.get(asset if asset != "USDC" else "USDT") or 1.0
        except Exception:
            rate = {"BTC": 60000.0, "ETH": 3000.0, "USDC": 1.0}.get(asset, 1.0)
        if asset in {"USDC", "USDT"}:
            amount = round(price_usd, 2)
            amount_str = f"{amount:.2f}"
        else:
            amount = round(price_usd / float(rate), 8)
            amount_str = f"{amount:.8f}".rstrip("0").rstrip(".")
        currency = asset
        pay_to_label = f"Coinbase {asset} deposit ({m['email']})"
        instructions = (
            f"Send exactly {amount_str} {asset} to the Coinbase deposit address. "
            f"Account email {m['email']}. Reference {inv_id}."
        )

    elif method.startswith("binance"):
        rail = "binance"
        asset = "USDT"
        if "btc" in method:
            asset = "BTC"
        elif "eth" in method:
            asset = "ETH"
        key = f"BINANCE_{asset}_ADDRESS"
        pay_to = (env.get(key) or "").strip()
        if not pay_to:
            return {
                "ok": False,
                "error": (
                    f"Binance {asset} address not set for {env.get('BINANCE_ACCOUNT_EMAIL') or m['email']}. "
                    f"Add {key} to ~/.config/sophyane/payments.env"
                ),
            }
        network = env.get("BINANCE_USDT_NETWORK", "TRC20") if asset == "USDT" else asset
        try:
            from sophyane.cloud.crypto_billing import fetch_rates

            rates = fetch_rates()
            rate = rates.get(asset) or 1.0
        except Exception:
            rate = 1.0 if asset == "USDT" else 60000.0
        if asset == "USDT":
            amount = round(price_usd, 2)
            amount_str = f"{amount:.2f}"
        else:
            amount = round(price_usd / float(rate), 8)
            amount_str = f"{amount:.8f}".rstrip("0").rstrip(".")
        currency = asset
        pay_to_label = f"Binance {asset} ({network}) · {m['email']}"
        instructions = (
            f"Send exactly {amount_str} {asset}"
            + (f" on {network}" if network else "")
            + f" to Binance deposit address. Memo/ref {inv_id}."
        )

    elif method in {"jazzcash", "easypaisa", "upaisa"}:
        rail = method
        labels = {"jazzcash": "JazzCash", "easypaisa": "EasyPaisa", "upaisa": "UPaisa"}
        label = labels[method]
        phone_key = f"{method.upper()}_PHONE"
        pay_to = (env.get(phone_key) or m["phone_local"] or m["phone"]).strip()
        pkr_rate = fetch_usd_pkr_rate()
        amount = round(price_usd * pkr_rate, 0)  # whole PKR
        # unique PKR offset for matching (1–99)
        amount = amount + secrets.randbelow(99) + 1
        amount_str = f"{int(amount)}"
        currency = "PKR"
        asset = "PKR"
        pay_to_label = f"{label} · {env.get(method.upper() + '_ACCOUNT_NAME') or m['name']}"
        instructions = (
            f"Send exactly Rs {amount_str} via {label} to {pay_to} "
            f"({pay_to_label}). Use reference/note: {inv_id}. "
            f"Merchant phone {m['phone']} · email {m['email']}."
        )
    else:
        return {"ok": False, "error": f"unsupported payment method {method}"}

    note = f"Sophyane {plan_id} · {inv_id} · {rail}"
    with _conn() as con:
        con.execute(
            """
            INSERT INTO rail_invoices(
              id,user_id,email,plan,rail,method,asset,network,currency,amount,amount_str,
              pay_to,pay_to_label,status,created_at,expires_at,note
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                inv_id,
                user_id,
                email,
                plan_id,
                rail,
                method,
                asset,
                network,
                currency,
                amount,
                amount_str,
                pay_to,
                pay_to_label,
                "pending",
                now,
                now + ttl * 60,
                note,
            ),
        )
        con.commit()

    return {
        "ok": True,
        "invoice_id": inv_id,
        "plan": plan_id,
        "rail": rail,
        "method": method,
        "asset": asset,
        "network": network,
        "currency": currency,
        "amount": amount,
        "amount_str": amount_str,
        "amount_fiat_usd": price_usd,
        "address": pay_to,  # UI reuse
        "pay_to": pay_to,
        "pay_to_label": pay_to_label,
        "merchant": m,
        "expires_at": now + ttl * 60,
        "ttl_min": ttl,
        "note": note,
        "instructions": instructions,
    }


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    # Prefer rail DB; fall back to crypto invoices
    with _conn() as con:
        row = con.execute("SELECT * FROM rail_invoices WHERE id=?", (invoice_id,)).fetchone()
    if row:
        return dict(row)
    try:
        from sophyane.cloud.crypto_billing import get_invoice as crypto_get

        return crypto_get(invoice_id)
    except Exception:
        return None


def mark_paid(invoice_id: str, *, txid: str = "", note: str = "") -> dict[str, Any]:
    inv = get_invoice(invoice_id)
    if not inv:
        return {"ok": False, "error": "invoice not found"}
    if str(inv.get("status")) == "paid":
        return {"ok": True, "already": True, "invoice": inv, "plan": inv.get("plan")}
    # crypto invoices (cry_*) use crypto_billing
    if invoice_id.startswith("cry_"):
        from sophyane.cloud.crypto_billing import mark_paid as crypto_paid

        return crypto_paid(invoice_id, txid=txid, note=note)
    now = time.time()
    with _conn() as con:
        con.execute(
            "UPDATE rail_invoices SET status=?, txid=?, paid_at=?, note=COALESCE(?, note) WHERE id=?",
            ("paid", txid or inv.get("txid") or "", now, note or None, invoice_id),
        )
        con.commit()
    inv = get_invoice(invoice_id)
    return {"ok": True, "invoice": inv, "plan": inv.get("plan") if inv else None}


def user_report_payment(invoice_id: str, user_id: str, txid: str = "") -> dict[str, Any]:
    if invoice_id.startswith("cry_"):
        from sophyane.cloud.crypto_billing import user_report_payment as crypto_report

        return crypto_report(invoice_id, user_id, txid=txid)
    inv = get_invoice(invoice_id)
    if not inv:
        return {"ok": False, "error": "invoice not found"}
    if inv.get("user_id") != user_id:
        return {"ok": False, "error": "invoice does not belong to this user"}
    with _conn() as con:
        con.execute(
            "UPDATE rail_invoices SET status=?, txid=?, note=? WHERE id=? AND status='pending'",
            (
                "awaiting_confirm",
                txid,
                f"user reported payment at {int(time.time())}",
                invoice_id,
            ),
        )
        con.commit()
    if txid and len(txid) >= 4:
        return mark_paid(invoice_id, txid=txid, note="user-submitted reference/txid")
    inv = get_invoice(invoice_id)
    return {
        "ok": True,
        "pending": True,
        "invoice": inv,
        "message": "Payment marked awaiting confirm. Provide JazzCash/EasyPaisa TID or crypto txid for faster activation.",
    }


def create_payout(
    *,
    user_id: str,
    rail: str,
    amount: float,
    currency: str,
    destination: str,
    note: str = "",
) -> dict[str, Any]:
    """Record a disbursement request. Live API send requires merchant API keys."""
    env = load_payments_env()
    rail = rail.lower().strip()
    allowed = {"jazzcash", "easypaisa", "upaisa", "binance", "coinbase", "monero", "kucoin"}
    if rail not in allowed:
        return {"ok": False, "error": f"unsupported payout rail {rail}"}
    if amount <= 0:
        return {"ok": False, "error": "amount must be positive"}
    dest = (destination or "").strip()
    if not dest:
        return {"ok": False, "error": "destination required (phone, address, or account id)"}
    pid = "po_" + secrets.token_hex(8)
    now = time.time()
    # Auto-complete only if operator mode (no live bank API without keys)
    status = "queued"
    api_ready = False
    if rail in {"binance", "coinbase", "kucoin"}:
        api_ready = bool(
            env.get(f"{rail.upper()}_API_KEY")
            or env.get(f"{rail.upper()}_API_SECRET")
            or env.get("COINBASE_API_KEY")
        )
    with _conn() as con:
        con.execute(
            """
            INSERT INTO rail_payouts(
              id,user_id,rail,method,amount,currency,destination,status,created_at,note
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pid,
                user_id,
                rail,
                rail,
                float(amount),
                currency.upper(),
                dest,
                status,
                now,
                note or f"payout via {rail}; api_ready={api_ready}",
            ),
        )
        con.commit()
    return {
        "ok": True,
        "payout_id": pid,
        "status": status,
        "rail": rail,
        "amount": amount,
        "currency": currency.upper(),
        "destination": dest,
        "api_ready": api_ready,
        "message": (
            "Payout queued. With exchange/mobile-wallet merchant API keys, "
            "Sophyane can auto-disburse; otherwise operator completes from the linked account "
            f"({merchant_identity(env)['email']} / {merchant_identity(env)['phone']})."
        ),
    }


def list_payouts(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM rail_payouts WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
