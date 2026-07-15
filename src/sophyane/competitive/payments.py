"""Multi-rail payments: Stripe + JazzCash + EasyPaisa + UPaisa + crypto + COD.
Loads secrets from ~/.config/sophyane/{stripe,payments,crypto}.env when present.
Never logs secrets. Falls back to demo mode if Stripe API unreachable.
"""
from __future__ import annotations
import json, os, time, uuid, hashlib, urllib.request, ssl
from pathlib import Path
from typing import Any

def _load_env_file(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

def load_payment_config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    home = Path.home() / ".config" / "sophyane"
    for name in ("stripe.env", "payments.env", "crypto.env"):
        cfg.update(_load_env_file(home / name))
    # env overrides
    for k, v in os.environ.items():
        if k.startswith(("STRIPE_", "JAZZCASH_", "EASYPAISA_", "UPAISA_", "COINBASE_", "BINANCE_", "MONERO_")):
            cfg[k] = v
    return cfg

def uid(prefix: str = "pay") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# Competitor benchmark → our undercut prices (document + bill)
PRICING_CATALOG = {
    "khaana": {
        "competitor": "Foodpanda",
        "currency": "PKR",
        "items": [
            {"sku": "delivery_fee", "name": "Delivery fee", "competitor_price": 120, "our_price": 40, "unit": "order"},
            {"sku": "service_fee", "name": "Service fee", "competitor_price": 50, "our_price": 15, "unit": "order"},
            {"sku": "pro_monthly", "name": "Khaana Pro (free delivery)", "competitor_price": 299, "our_price": 99, "unit": "month"},
        ],
    },
    "mypharma": {
        "competitor": "DVAGO",
        "currency": "PKR",
        "items": [
            {"sku": "delivery_fee", "name": "Pharmacy delivery", "competitor_price": 99, "our_price": 49, "unit": "order"},
            {"sku": "rx_review", "name": "Pharmacist RX review", "competitor_price": 200, "our_price": 50, "unit": "order"},
            {"sku": "subscription", "name": "Chronic refill plan", "competitor_price": 499, "our_price": 149, "unit": "month"},
        ],
    },
    "bijli": {
        "competitor": "Daraz / solar dealers",
        "currency": "PKR",
        "items": [
            {"sku": "platform_fee", "name": "Marketplace fee %", "competitor_price": 12, "our_price": 4, "unit": "percent"},
            {"sku": "install_booking", "name": "Install booking deposit", "competitor_price": 5000, "our_price": 1500, "unit": "job"},
            {"sku": "warranty_ext", "name": "Extended warranty 1y", "competitor_price": 8000, "our_price": 2999, "unit": "year"},
        ],
    },
    "laibabadar": {
        "competitor": "Foodpanda restaurant",
        "currency": "PKR",
        "items": [
            {"sku": "delivery_fee", "name": "Brand delivery", "competitor_price": 120, "our_price": 50, "unit": "order"},
            {"sku": "reservation", "name": "Table reservation hold", "competitor_price": 500, "our_price": 0, "unit": "booking"},
            {"sku": "loyalty_boost", "name": "Double points day", "competitor_price": 200, "our_price": 0, "unit": "promo"},
        ],
    },
    "rangoons": {
        "competitor": "Shopify + WA Business",
        "currency": "USD",
        "items": [
            {"sku": "starter", "name": "SME store plan", "competitor_price": 29, "our_price": 9.99, "unit": "month"},
            {"sku": "wa_commerce", "name": "WhatsApp commerce add-on", "competitor_price": 15, "our_price": 3.99, "unit": "month"},
            {"sku": "txn_fee", "name": "Transaction fee %", "competitor_price": 2.9, "our_price": 1.5, "unit": "percent"},
        ],
    },
    "vps": {
        "competitor": "DigitalOcean",
        "currency": "USD",
        "items": [
            {"sku": "s-1vcpu-1gb", "name": "1 vCPU / 1GB", "competitor_price": 6, "our_price": 2.99, "unit": "month"},
            {"sku": "s-2vcpu-2gb", "name": "2 vCPU / 2GB", "competitor_price": 12, "our_price": 5.99, "unit": "month"},
            {"sku": "s-4vcpu-8gb", "name": "4 vCPU / 8GB", "competitor_price": 48, "our_price": 19.99, "unit": "month"},
            {"sku": "backup", "name": "Weekly backups", "competitor_price": 1.2, "our_price": 0.49, "unit": "month"},
            {"sku": "lb", "name": "Load balancer", "competitor_price": 12, "our_price": 4.99, "unit": "month"},
        ],
    },
    "sophyane": {
        "competitor": "Claude Pro / Cursor Pro",
        "currency": "USD",
        "items": [
            {"sku": "agent_pro", "name": "Sophyane Agent Pro", "competitor_price": 20, "our_price": 7.99, "unit": "month"},
            {"sku": "team", "name": "Team (5 seats)", "competitor_price": 100, "our_price": 29.99, "unit": "month"},
            {"sku": "api_1m", "name": "API 1M tokens pack", "competitor_price": 15, "our_price": 4.99, "unit": "pack"},
        ],
    },
    "shmry": {
        "competitor": "Datadog",
        "currency": "USD",
        "items": [
            {"sku": "host", "name": "Host monitoring", "competitor_price": 15, "our_price": 4.99, "unit": "host/month"},
            {"sku": "logs_gb", "name": "Log ingest per GB", "competitor_price": 0.10, "our_price": 0.03, "unit": "GB"},
            {"sku": "apm", "name": "APM host", "competitor_price": 31, "our_price": 9.99, "unit": "host/month"},
        ],
    },
    "huobz": {
        "competitor": "OpenAI API / Ollama cloud",
        "currency": "USD",
        "items": [
            {"sku": "edge_node", "name": "Edge node license", "competitor_price": 25, "our_price": 7.99, "unit": "month"},
            {"sku": "coder_pro", "name": "AI Coder Pro", "competitor_price": 20, "our_price": 6.99, "unit": "month"},
            {"sku": "tokens_1m", "name": "1M inference tokens", "competitor_price": 10, "our_price": 2.99, "unit": "pack"},
        ],
    },
    "nifdu": {
        "competitor": "news apps premium",
        "currency": "PKR",
        "items": [
            {"sku": "adfree", "name": "Ad-free news", "competitor_price": 399, "our_price": 99, "unit": "month"},
            {"sku": "alerts", "name": "Breaking alerts SMS", "competitor_price": 199, "our_price": 49, "unit": "month"},
        ],
    },
    "darulsakina": {
        "competitor": "community donation platforms",
        "currency": "PKR",
        "items": [
            {"sku": "zakat_processing", "name": "Zakat processing fee %", "competitor_price": 2.9, "our_price": 0.5, "unit": "percent"},
            {"sku": "membership", "name": "Member support (optional)", "competitor_price": 500, "our_price": 100, "unit": "month"},
        ],
    },
    "cast": {
        "competitor": "Chromecast hardware / apps",
        "currency": "USD",
        "items": [
            {"sku": "pro", "name": "Cast Pro (multi-room)", "competitor_price": 4.99, "our_price": 1.99, "unit": "month"},
            {"sku": "lifetime", "name": "Lifetime OSS Pro", "competitor_price": 49, "our_price": 14.99, "unit": "once"},
        ],
    },
    "xerus": {
        "competitor": "TikTok / Reels boosts",
        "currency": "USD",
        "items": [
            {"sku": "boost_1k", "name": "Boost 1k views", "competitor_price": 5, "our_price": 1.49, "unit": "boost"},
            {"sku": "creator", "name": "Creator tools", "competitor_price": 9.99, "our_price": 2.99, "unit": "month"},
            {"sku": "live_gift_fee", "name": "Live gift fee %", "competitor_price": 50, "our_price": 15, "unit": "percent"},
        ],
    },
}

RAILS = [
    {"id": "stripe", "name": "Stripe (card)", "currencies": ["USD", "PKR", "EUR"]},
    {"id": "jazzcash", "name": "JazzCash", "currencies": ["PKR"]},
    {"id": "easypaisa", "name": "EasyPaisa", "currencies": ["PKR"]},
    {"id": "upaisa", "name": "UPaisa", "currencies": ["PKR"]},
    {"id": "coinbase", "name": "Coinbase (BTC/ETH/USDC)", "currencies": ["USD", "crypto"]},
    {"id": "binance", "name": "Binance Pay (USDT/BTC)", "currencies": ["USD", "crypto"]},
    {"id": "monero", "name": "Monero", "currencies": ["XMR"]},
    {"id": "cod", "name": "Cash on delivery", "currencies": ["PKR"]},
    {"id": "bank", "name": "Bank transfer", "currencies": ["PKR", "USD"]},
]

_INVOICES: dict[str, dict] = {}

def list_rails(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_payment_config()
    out = []
    for r in RAILS:
        enabled = True
        if r["id"] == "stripe":
            enabled = bool(cfg.get("STRIPE_SECRET_KEY"))
        elif r["id"] == "jazzcash":
            enabled = cfg.get("JAZZCASH_ENABLED", "true").lower() != "false"
        elif r["id"] == "easypaisa":
            enabled = cfg.get("EASYPAISA_ENABLED", "true").lower() != "false"
        elif r["id"] == "upaisa":
            enabled = cfg.get("UPAISA_ENABLED", "true").lower() != "false"
        elif r["id"] == "coinbase":
            enabled = cfg.get("COINBASE_ENABLED", "true").lower() != "false"
        elif r["id"] == "binance":
            enabled = cfg.get("BINANCE_ENABLED", "true").lower() != "false"
        elif r["id"] == "monero":
            enabled = cfg.get("MONERO_ENABLED", "true").lower() != "false"
        out.append({**r, "enabled": enabled, "demo": r["id"] == "stripe" and not cfg.get("STRIPE_SECRET_KEY")})
    return out

def pricing_for(product: str) -> dict:
    cat = PRICING_CATALOG.get(product) or {"competitor": "market", "currency": "USD", "items": []}
    items = []
    for it in cat["items"]:
        save = round((it["competitor_price"] - it["our_price"]) / max(it["competitor_price"], 0.0001) * 100, 1)
        items.append({**it, "savings_percent": save, "undercut": True})
    return {
        "product": product,
        "competitor": cat["competitor"],
        "currency": cat["currency"],
        "policy": "Prices set ≥40% below typical competitor list rates where comparable.",
        "items": items,
        "rails": list_rails(),
    }

def _stripe_payment_intent(amount_minor: int, currency: str, description: str, cfg: dict) -> dict | None:
    key = cfg.get("STRIPE_SECRET_KEY")
    if not key:
        return None
    # amount already in smallest unit for USD cents; for PKR Stripe may use integer rupees depending on account
    data = (
        f"amount={amount_minor}&currency={currency.lower()}"
        f"&description={urllib.request.quote(description)}"
        f"&payment_method_types[]=card"
        f"&metadata[source]=badrpk_portfolio"
    ).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/payment_intents",
        data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "fallback": True}

def create_invoice(
    product: str,
    amount: float,
    currency: str,
    method: str = "stripe",
    description: str = "",
    customer: str = "guest",
    sku: str | None = None,
    metadata: dict | None = None,
) -> dict:
    cfg = load_payment_config()
    method = (method or "stripe").lower()
    inv_id = uid("inv")
    # normalize amount
    if sku:
        for it in (PRICING_CATALOG.get(product) or {}).get("items") or []:
            if it["sku"] == sku:
                amount = float(it["our_price"])
                currency = (PRICING_CATALOG[product].get("currency") or currency)
                description = description or it["name"]
                break

    invoice: dict[str, Any] = {
        "id": inv_id,
        "product": product,
        "amount": round(float(amount), 2),
        "currency": currency.upper(),
        "method": method,
        "description": description or f"{product} payment",
        "customer": customer,
        "sku": sku,
        "status": "pending",
        "created_at": iso(),
        "metadata": metadata or {},
        "pay_instructions": {},
        "stripe": None,
    }

    if method == "stripe":
        # minor units: USD cents; PKR as whole (zero-decimal often)
        cur = currency.upper()
        if cur in ("JPY", "KRW", "PKR"):  # treat as zero-decimal for simplicity in demo
            minor = int(round(float(amount)))
        else:
            minor = int(round(float(amount) * 100))
        pi = _stripe_payment_intent(minor, cur, invoice["description"], cfg)
        if pi and pi.get("id") and not pi.get("fallback"):
            invoice["stripe"] = {
                "payment_intent_id": pi.get("id"),
                "client_secret": pi.get("client_secret"),
                "status": pi.get("status"),
            }
            invoice["status"] = pi.get("status") or "requires_payment_method"
            invoice["pay_instructions"] = {
                "type": "stripe_payment_intent",
                "client_secret": pi.get("client_secret"),
                "publishable_key_set": bool(cfg.get("STRIPE_PUBLISHABLE_KEY")),
            }
        else:
            invoice["status"] = "pending_demo"
            invoice["stripe"] = {"demo": True, "error": (pi or {}).get("error"), "note": "Stripe key missing or API error; demo invoice created"}
            invoice["pay_instructions"] = {"type": "demo_card", "use_test_card": "4242 4242 4242 4242", "message": "Configure STRIPE_SECRET_KEY for live intents"}
    elif method == "jazzcash":
        invoice["pay_instructions"] = {
            "type": "jazzcash",
            "account_phone": cfg.get("JAZZCASH_PHONE") or "configured_in_payments.env",
            "account_name": cfg.get("JAZZCASH_ACCOUNT_NAME") or "Merchant",
            "send_amount": invoice["amount"],
            "reference": inv_id,
        }
    elif method == "easypaisa":
        invoice["pay_instructions"] = {
            "type": "easypaisa",
            "account_phone": cfg.get("EASYPAISA_PHONE") or "configured_in_payments.env",
            "account_name": cfg.get("EASYPAISA_ACCOUNT_NAME") or "Merchant",
            "send_amount": invoice["amount"],
            "reference": inv_id,
        }
    elif method == "upaisa":
        invoice["pay_instructions"] = {
            "type": "upaisa",
            "account_phone": cfg.get("UPAISA_PHONE") or "configured_in_payments.env",
            "send_amount": invoice["amount"],
            "reference": inv_id,
        }
    elif method == "coinbase":
        invoice["pay_instructions"] = {
            "type": "coinbase",
            "btc": cfg.get("COINBASE_BTC_ADDRESS") or "set_COINBASE_BTC_ADDRESS",
            "eth": cfg.get("COINBASE_ETH_ADDRESS") or "set_COINBASE_ETH_ADDRESS",
            "usdc": cfg.get("COINBASE_USDC_ADDRESS") or "set_COINBASE_USDC_ADDRESS",
            "reference": inv_id,
        }
    elif method == "binance":
        invoice["pay_instructions"] = {
            "type": "binance",
            "usdt": cfg.get("BINANCE_USDT_ADDRESS") or "set_BINANCE_USDT_ADDRESS",
            "network": cfg.get("BINANCE_USDT_NETWORK") or "TRC20",
            "btc": cfg.get("BINANCE_BTC_ADDRESS"),
            "reference": inv_id,
        }
    elif method == "monero":
        invoice["pay_instructions"] = {
            "type": "monero",
            "address": cfg.get("MONERO_PRIMARY_ADDRESS") or cfg.get("MONERO_SUBADDRESS") or "set_MONERO_ADDRESS",
            "reference": inv_id,
        }
    elif method == "cod":
        invoice["status"] = "cod_pending"
        invoice["pay_instructions"] = {"type": "cod", "message": "Pay cash to rider/agent", "reference": inv_id}
    elif method == "bank":
        invoice["pay_instructions"] = {"type": "bank", "message": "Transfer and send proof", "reference": inv_id, "email": cfg.get("MERCHANT_EMAIL")}
    else:
        invoice["status"] = "error"
        invoice["pay_instructions"] = {"error": "unknown_method", "allowed": [r["id"] for r in RAILS]}

    _INVOICES[inv_id] = invoice
    return invoice

def get_invoice(inv_id: str) -> dict | None:
    return _INVOICES.get(inv_id)

def mark_paid(inv_id: str, proof: str = "") -> dict | None:
    inv = _INVOICES.get(inv_id)
    if not inv:
        return None
    inv["status"] = "paid"
    inv["paid_at"] = iso()
    inv["proof"] = proof[:500]
    return inv

def savings_summary(product: str) -> dict:
    p = pricing_for(product)
    rows = []
    for it in p["items"]:
        if it["unit"] == "percent":
            rows.append({"sku": it["sku"], "you_save": f"{it['savings_percent']}% fee reduction vs {p['competitor']}"})
        else:
            rows.append({
                "sku": it["sku"],
                "competitor": it["competitor_price"],
                "ours": it["our_price"],
                "save": round(it["competitor_price"] - it["our_price"], 2),
                "currency": p["currency"],
            })
    return {"product": product, "competitor": p["competitor"], "savings": rows}
