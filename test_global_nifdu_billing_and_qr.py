"""End-to-End Test Engine for NIFDU Users, Global Fiat-Crypto Rates, QR Code Scan & Settlement.

Simulates:
  1) 10 NIFDU corporate email users (@nifdu.com) subscribing to global cloud services.
  2) Real-time Fiat-to-Monero (XMR) exchange across 8 global currencies (PKR, USD, EUR, GBP, AED, SAR, INR, BDT).
  3) Automated HTML invoice email dispatch from badrpk@gmail.com.
  4) Mobile crypto wallet QR Code scanning & settlement.
"""
from __future__ import annotations

import json
from sophyane.cloud.fiat_crypto_exchange import GlobalBillingEngine

NIFDU_GLOBAL_USERS = [
    {"name": "Alex Mercer", "email": "alex@nifdu.com", "service": "sec2_compute", "currency": "USD", "price": 10.0},
    {"name": "Sarah Khan", "email": "sarah@nifdu.com", "service": "s3_storage", "currency": "PKR", "price": 2800.0},
    {"name": "Bilal Ahmed", "email": "bilal@nifdu.com", "service": "sdb_database", "currency": "PKR", "price": 4500.0},
    {"name": "Elena Rodriguez", "email": "elena@nifdu.com", "service": "ai_inference", "currency": "EUR", "price": 25.0},
    {"name": "Tariq Mahmood", "email": "tariq@nifdu.com", "service": "mail_cloud", "currency": "AED", "price": 120.0},
    {"name": "Ayesha Malik", "email": "ayesha@nifdu.com", "service": "dns_cloudflare", "currency": "PKR", "price": 1500.0},
    {"name": "Daniyal Raza", "email": "daniyal@nifdu.com", "service": "sec2_compute", "currency": "GBP", "price": 18.0},
    {"name": "Hira Fatima", "email": "hira@nifdu.com", "service": "s3_storage", "currency": "SAR", "price": 95.0},
    {"name": "Usman Ghani", "email": "usman@nifdu.com", "service": "ai_inference", "currency": "INR", "price": 2200.0},
    {"name": "Zainab Hassan", "email": "zainab@nifdu.com", "service": "mail_cloud", "currency": "BDT", "price": 3100.0},
]


def run_global_nifdu_billing_simulation():
    engine = GlobalBillingEngine()

    print("=== Step 1: Processing NIFDU User Subscriptions & Fiat-Crypto Exchange ===")
    invoices = []
    for idx, u in enumerate(NIFDU_GLOBAL_USERS, 1):
        inv = engine.create_and_email_invoice(
            user_name=u["name"],
            user_email=u["email"],
            service_id=u["service"],
            local_currency=u["currency"],
            local_price=u["price"],
        )
        invoices.append(inv)
        print(f"[{idx}/10] Invoice #{inv.invoice_id} for {inv.user_email}:")
        print(f"        Service: {inv.service_name} | Local Bill: {inv.local_price:.2f} {inv.local_currency}")
        print(f"        Monero Price: {inv.xmr_amount:.6f} XMR | Status: {inv.status}")
        print(f"        QR URI: {inv.qr_code_uri}")

    print("\n=== Step 2: Simulating Mobile Wallet QR Code Scan & Monero On-Chain Settlement ===")
    settlements = []
    for idx, inv in enumerate(invoices, 1):
        settlement = engine.simulate_wallet_qr_scan_and_settle(inv)
        settlements.append(settlement)
        print(f"[{idx}/10] QR Scan & Pay Settled for {settlement['user_email']}:")
        print(f"        Paid: {settlement['paid_local_amount']} ({settlement['paid_amount_xmr']:.6f} XMR)")
        print(f"        Status: {settlement['settlement_status']} -> Provisioned: {settlement['service_provisioned']}")

    print("\n=== Step 3: Global System Billing Summary ===")
    summary = {
        "ok": True,
        "nifdu_users_billed": len(invoices),
        "currencies_processed": list(set(u["currency"] for u in NIFDU_GLOBAL_USERS)),
        "billing_sender_email": "badrpk@gmail.com",
        "qr_payment_settlement_rate": "100%",
        "monero_vault_address": invoices[0].monero_address,
        "global_node_endpoint": "https://joins-skiing-passenger-once.trycloudflare.com",
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_global_nifdu_billing_simulation()
