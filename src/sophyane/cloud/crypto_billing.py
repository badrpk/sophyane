"""Crypto payments: Monero (primary) + KuCoin deposit addresses (USDT/BTC/ETH).

Monero: unique invoice amounts for matching; optional wallet-RPC confirm when running.
KuCoin: static deposit addresses from crypto.env, or auto-fetch via KuCoin API keys.
Owner account: CRYPTO_OWNER_EMAIL / KUCOIN_ACCOUNT_EMAIL (badrpk@gmail.com).
"""

from __future__ import annotations

import hashlib
import hmac
import base64
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

CRYPTO_ENV = Path.home() / ".config" / "sophyane" / "crypto.env"
DB_PATH = Path.home() / ".local" / "state" / "sophyane" / "cloud" / "crypto_invoices.db"


def load_crypto_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith(("MONERO_", "KUCOIN_", "CRYPTO_")):
            env[k] = v.strip()
    if CRYPTO_ENV.exists():
        for line in CRYPTO_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _monero_receive_address(env: dict[str, str] | None = None) -> str:
    """Prefer primary; fall back to subaddress used by superapp."""
    e = env or load_crypto_env()
    primary = e.get("MONERO_PRIMARY_ADDRESS", "").strip()
    sub = e.get("MONERO_SUBADDRESS", "").strip()
    if len(primary) >= 90:
        return primary
    if len(sub) >= 90:
        return sub
    return primary or sub


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_invoices (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          email TEXT,
          plan TEXT NOT NULL,
          method TEXT NOT NULL,
          asset TEXT NOT NULL,
          network TEXT,
          address TEXT NOT NULL,
          amount_fiat REAL NOT NULL,
          fiat TEXT NOT NULL,
          amount_crypto REAL NOT NULL,
          amount_crypto_str TEXT NOT NULL,
          status TEXT NOT NULL,
          txid TEXT,
          created_at REAL NOT NULL,
          expires_at REAL NOT NULL,
          paid_at REAL,
          note TEXT
        )
        """
    )
    con.commit()
    return con


def kucoin_api_configured(env: dict[str, str] | None = None) -> bool:
    e = env or load_crypto_env()
    return bool(e.get("KUCOIN_API_KEY") and e.get("KUCOIN_API_SECRET") and e.get("KUCOIN_API_PASSPHRASE"))


def kucoin_request(method: str, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """Signed KuCoin REST call (deposit addresses, etc.)."""
    env = load_crypto_env()
    key = env.get("KUCOIN_API_KEY") or ""
    secret = env.get("KUCOIN_API_SECRET") or ""
    passphrase = env.get("KUCOIN_API_PASSPHRASE") or ""
    base = (env.get("KUCOIN_API_BASE") or "https://api.kucoin.com").rstrip("/")
    if not (key and secret and passphrase):
        raise RuntimeError("KuCoin API keys not configured in crypto.env")
    qs = ""
    if params:
        qs = "?" + urllib.parse.urlencode(params)
    endpoint = path + qs
    now_ms = str(int(time.time() * 1000))
    # KC-API-SIGN = base64(hmac_sha256(secret, timestamp + method + endpoint + body))
    prehash = now_ms + method.upper() + endpoint + ""
    sign = base64.b64encode(hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
    pass_sign = base64.b64encode(hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256).digest()).decode()
    headers = {
        "KC-API-KEY": key,
        "KC-API-SIGN": sign,
        "KC-API-TIMESTAMP": now_ms,
        "KC-API-PASSPHRASE": pass_sign,
        "KC-API-KEY-VERSION": "2",
        "Content-Type": "application/json",
        "User-Agent": "SophyaneCrypto/17.2",
    }
    req = urllib.request.Request(base + endpoint, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") not in (None, "200000", 200000, "200"):
        raise RuntimeError(str(data.get("msg") or data))
    return data.get("data") if isinstance(data, dict) and "data" in data else data


def fetch_kucoin_deposit_address(currency: str, chain: str = "") -> dict[str, Any]:
    """Return {address, memo, chain, currency} from KuCoin API."""
    currency = currency.upper()
    params: dict[str, str] = {"currency": currency}
    if chain:
        params["chain"] = chain
    try:
        data = kucoin_request("GET", "/api/v1/deposit-addresses", params)
    except Exception:
        # v2 endpoint
        data = kucoin_request("GET", "/api/v2/deposit-addresses", params)
    if isinstance(data, list) and data:
        row = data[0]
    elif isinstance(data, dict):
        row = data
    else:
        return {"ok": False, "error": "no deposit address returned"}
    return {
        "ok": True,
        "currency": currency,
        "address": str(row.get("address") or row.get("address") or ""),
        "memo": str(row.get("memo") or row.get("paymentId") or ""),
        "chain": str(row.get("chain") or chain or ""),
        "raw": row,
    }


def resolve_kucoin_address(asset: str, env: dict[str, str] | None = None) -> tuple[str, str]:
    """(address, network) from env static config or live KuCoin API."""
    e = env or load_crypto_env()
    asset = asset.upper()
    key = f"KUCOIN_{asset}_ADDRESS"
    addr = (e.get(key) or "").strip()
    network = e.get("KUCOIN_USDT_NETWORK", "TRC20") if asset == "USDT" else asset
    if addr:
        return addr, network
    if kucoin_api_configured(e):
        chain = e.get("KUCOIN_USDT_NETWORK", "TRC20") if asset == "USDT" else ""
        try:
            got = fetch_kucoin_deposit_address(asset, chain=chain)
            if got.get("ok") and got.get("address"):
                return str(got["address"]), str(got.get("chain") or network)
        except Exception:
            pass
    return "", network


def public_config() -> dict[str, Any]:
    env = load_crypto_env()
    xmr = _monero_receive_address(env)
    monero_on = env.get("MONERO_ENABLED", "1") == "1" and len(xmr) >= 90
    kucoin_on = env.get("KUCOIN_ENABLED", "1") == "1"
    owner = env.get("CRYPTO_OWNER_EMAIL") or env.get("KUCOIN_ACCOUNT_EMAIL") or "badrpk@gmail.com"
    methods = []
    if monero_on:
        methods.append(
            {
                "id": "monero",
                "name": "Monero (XMR)",
                "asset": "XMR",
                "private": True,
                "address_preview": xmr[:12] + "…" + xmr[-8:] if xmr else "",
                "owner": owner,
            }
        )
    if kucoin_on:
        for asset, key, netkey in (
            ("USDT", "KUCOIN_USDT_ADDRESS", "KUCOIN_USDT_NETWORK"),
            ("BTC", "KUCOIN_BTC_ADDRESS", None),
            ("ETH", "KUCOIN_ETH_ADDRESS", None),
        ):
            addr, network = resolve_kucoin_address(asset, env)
            if addr:
                methods.append(
                    {
                        "id": f"kucoin_{asset.lower()}",
                        "name": f"KuCoin {asset}",
                        "asset": asset,
                        "network": network or (env.get(netkey or "", "") if netkey else ""),
                        "address_preview": addr[:10] + "…" + addr[-6:],
                        "exchange": "kucoin",
                        "account": env.get("KUCOIN_ACCOUNT_EMAIL") or owner,
                    }
                )
        if not any(m.get("exchange") == "kucoin" for m in methods):
            api_ready = kucoin_api_configured(env)
            methods.append(
                {
                    "id": "kucoin_setup",
                    "name": "KuCoin (deposit address needed)",
                    "asset": "USDT",
                    "needs_setup": True,
                    "account": env.get("KUCOIN_ACCOUNT_EMAIL") or owner,
                    "api_configured": api_ready,
                    "hint": (
                        "KuCoin account linked ("
                        + (env.get("KUCOIN_ACCOUNT_EMAIL") or owner)
                        + "). Add KUCOIN_USDT_ADDRESS from KuCoin → Assets → Deposit (TRC20), "
                        "or set KUCOIN_API_KEY/SECRET/PASSPHRASE for auto-fetch."
                    ),
                }
            )
    return {
        "ok": True,
        "enabled": bool(methods),
        "methods": methods,
        "monero_enabled": monero_on,
        "kucoin_enabled": kucoin_on and any(m.get("exchange") == "kucoin" for m in methods),
        "kucoin_account": env.get("KUCOIN_ACCOUNT_EMAIL") or owner,
        "owner_email": owner,
        "note": (
            "Pay with Monero (local wallet) or KuCoin deposit (USDT/BTC/ETH). "
            f"Merchant account: {owner}. Plans activate after confirmation."
        ),
    }


def _http_json(url: str, timeout: float = 12.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "SophyaneCrypto/17.2", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_rates() -> dict[str, float]:
    """USD rates for XMR/BTC/ETH/USDT."""
    rates = {"USDT": 1.0, "USD": 1.0}
    try:
        data = _http_json(
            "https://api.coingecko.com/api/v3/simple/price?ids=monero,bitcoin,ethereum,tether&vs_currencies=usd"
        )
        rates["XMR"] = float(data.get("monero", {}).get("usd") or 0) or 150.0
        rates["BTC"] = float(data.get("bitcoin", {}).get("usd") or 0) or 60000.0
        rates["ETH"] = float(data.get("ethereum", {}).get("usd") or 0) or 3000.0
        rates["USDT"] = float(data.get("tether", {}).get("usd") or 1.0) or 1.0
    except Exception:
        rates.update({"XMR": 150.0, "BTC": 60000.0, "ETH": 3000.0, "USDT": 1.0})
    return rates


def plan_price_usd(plan_id: str) -> float:
    plan = PLANS.get(plan_id) or {}
    return float(plan.get("price_usd_month") or 0)


def _unique_xmr_amount(base: float) -> tuple[float, str]:
    """Slight unique offset so payments can be matched without subaddresses."""
    # 12 decimal places typical; use micro-offset from random
    offset = (secrets.randbelow(9000) + 1000) * 1e-8  # 0.00000001 .. 0.00009
    amount = round(base + offset, 8)
    return amount, f"{amount:.8f}"


def create_invoice(
    *,
    user_id: str,
    email: str,
    plan_id: str,
    method: str = "monero",
) -> dict[str, Any]:
    plan = PLANS.get(plan_id)
    if not plan:
        return {"ok": False, "error": f"unknown plan {plan_id}"}
    price = plan_price_usd(plan_id)
    if price <= 0:
        return {"ok": False, "error": "plan is free — no crypto payment needed", "free": True}

    env = load_crypto_env()
    rates = fetch_rates()
    ttl = int(env.get("CRYPTO_INVOICE_TTL_MIN") or 90)
    now = time.time()
    inv_id = "cry_" + secrets.token_hex(8)

    method = (method or "monero").lower()
    if method in {"monero", "xmr"}:
        addr = _monero_receive_address(env)
        if len(addr) < 90:
            return {"ok": False, "error": "Monero address not configured in ~/.config/sophyane/crypto.env"}
        xmr_rate = rates.get("XMR") or 150.0
        base_xmr = price / xmr_rate
        amount, amount_str = _unique_xmr_amount(base_xmr)
        asset, network = "XMR", "monero"
        method_id = "monero"
        pay_uri = f"monero:{addr}?tx_amount={amount_str}"
    elif method.startswith("kucoin"):
        asset = "USDT"
        if "btc" in method:
            asset = "BTC"
        elif "eth" in method:
            asset = "ETH"
        addr, network = resolve_kucoin_address(asset, env)
        if not addr:
            return {
                "ok": False,
                "error": (
                    f"KuCoin {asset} deposit address not set for account "
                    f"{env.get('KUCOIN_ACCOUNT_EMAIL') or 'badrpk@gmail.com'}. "
                    f"Paste address into KUCOIN_{asset}_ADDRESS in ~/.config/sophyane/crypto.env "
                    "(KuCoin → Assets → Deposit), or add KuCoin API keys for auto-fetch."
                ),
            }
        rate = rates.get(asset) or 1.0
        amount = round(price / rate, 8 if asset != "USDT" else 2)
        amount_str = f"{amount:.8f}".rstrip("0").rstrip(".") if asset != "USDT" else f"{amount:.2f}"
        method_id = f"kucoin_{asset.lower()}"
        pay_uri = ""
    else:
        return {"ok": False, "error": f"unsupported method {method}"}

    note = f"Sophyane {plan_id} plan · invoice {inv_id} · user {user_id[:8]}"
    with _conn() as con:
        con.execute(
            """
            INSERT INTO crypto_invoices(
              id,user_id,email,plan,method,asset,network,address,amount_fiat,fiat,
              amount_crypto,amount_crypto_str,status,created_at,expires_at,note
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                inv_id,
                user_id,
                email,
                plan_id,
                method_id,
                asset,
                network,
                addr,
                price,
                "USD",
                amount,
                amount_str,
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
        "method": method_id,
        "asset": asset,
        "network": network,
        "address": addr,
        "amount_fiat_usd": price,
        "amount_crypto": amount,
        "amount_crypto_str": amount_str,
        "pay_uri": pay_uri,
        "expires_at": now + ttl * 60,
        "ttl_min": ttl,
        "note": note,
        "instructions": (
            f"Send exactly {amount_str} {asset}"
            + (f" ({network})" if network else "")
            + f" to the address. Include reference {inv_id} in memo if the network supports it. "
            "After sending, click “I have paid” or wait for auto-confirm (Monero RPC)."
        ),
        "rates": {k: rates[k] for k in ("XMR", "BTC", "ETH", "USDT") if k in rates},
    }


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM crypto_invoices WHERE id=?", (invoice_id,)).fetchone()
    return dict(row) if row else None


def list_user_invoices(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM crypto_invoices WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_paid(invoice_id: str, *, txid: str = "", note: str = "") -> dict[str, Any]:
    inv = get_invoice(invoice_id)
    if not inv:
        return {"ok": False, "error": "invoice not found"}
    if inv["status"] == "paid":
        return {"ok": True, "already": True, "invoice": inv}
    if inv["expires_at"] < time.time() and inv["status"] == "pending":
        return {"ok": False, "error": "invoice expired — create a new one"}
    now = time.time()
    with _conn() as con:
        con.execute(
            "UPDATE crypto_invoices SET status=?, txid=?, paid_at=?, note=COALESCE(?, note) WHERE id=?",
            ("paid", txid or inv.get("txid") or "", now, note or None, invoice_id),
        )
        con.commit()
    inv = get_invoice(invoice_id)
    return {"ok": True, "invoice": inv, "plan": inv["plan"] if inv else None}


def user_report_payment(invoice_id: str, user_id: str, txid: str = "") -> dict[str, Any]:
    inv = get_invoice(invoice_id)
    if not inv:
        return {"ok": False, "error": "invoice not found"}
    if inv["user_id"] != user_id:
        return {"ok": False, "error": "invoice does not belong to this user"}
    # Mark as awaiting_confirm; auto-confirm monero if RPC sees funds (best-effort)
    with _conn() as con:
        con.execute(
            "UPDATE crypto_invoices SET status=?, txid=?, note=? WHERE id=? AND status='pending'",
            (
                "awaiting_confirm",
                txid,
                f"user reported payment at {int(time.time())}",
                invoice_id,
            ),
        )
        con.commit()
    auto = try_auto_confirm_monero(invoice_id)
    if auto.get("ok") and auto.get("paid"):
        return auto
    # For KuCoin / no RPC: trust user report for small plans after txid provided, else awaiting
    if txid and len(txid) >= 8:
        # Mark paid on self-report with txid (operator can dispute); suitable for small SaaS
        return mark_paid(invoice_id, txid=txid, note="user-submitted txid")
    inv = get_invoice(invoice_id)
    return {
        "ok": True,
        "pending": True,
        "invoice": inv,
        "message": "Payment marked awaiting confirm. Provide txid for faster activation, or wait for Monero RPC detection.",
    }


def monero_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    env = load_crypto_env()
    url = env.get("MONERO_RPC_URL") or "http://127.0.0.1:18082/json_rpc"
    user = env.get("MONERO_RPC_USER") or ""
    password = env.get("MONERO_RPC_PASS") or ""
    payload = json.dumps({"jsonrpc": "2.0", "id": "0", "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    if user:
        import base64

        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode())
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("result") or {}


def try_auto_confirm_monero(invoice_id: str) -> dict[str, Any]:
    inv = get_invoice(invoice_id)
    if not inv or inv["asset"] != "XMR":
        return {"ok": False, "paid": False}
    try:
        # get_transfers in requires unlocked/in
        result = monero_rpc("get_transfers", {"in": True, "pool": True})
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "paid": False, "rpc_error": str(error)}

    target = float(inv["amount_crypto"])
    # match amount within 1e-8
    for bucket in ("in", "pool"):
        for tx in result.get(bucket) or []:
            try:
                amt = float(tx.get("amount", 0)) / 1e12  # atomic units
            except Exception:
                continue
            if abs(amt - target) < 1e-7:
                txid = str(tx.get("txid") or tx.get("tx_hash") or "")
                return mark_paid(invoice_id, txid=txid, note="auto monero-rpc match")
    return {"ok": True, "paid": False, "message": "no matching transfer yet"}
