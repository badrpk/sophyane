"""Global Fiat-to-Crypto Exchange & Global Billing Engine for Sophyane.

Supports:
  1) Multi-currency conversion (PKR, USD, EUR, GBP, AED, SAR, INR, BDT -> Monero XMR).
  2) QR Code generator for mobile wallet scanning (monero:47EhKrcA...?tx_amount=...).
  3) Invoice dispatch via badrpk@gmail.com to @nifdu.com email accounts.
  4) Local wallet settlement and global service provisioning.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sophyane.cloud.cloud_services import CLOUD_SERVICES_CATALOG, CloudServicesManager
from sophyane.cloud.gmail_oauth import GmailOAuthManager
from sophyane.cloud.messaging import send_email


# Global Exchange Rates (Base: 1 XMR = $160 USD)
FIAT_RATES_PER_USD: dict[str, float] = {
    "USD": 1.0,
    "PKR": 278.50,
    "EUR": 0.92,
    "GBP": 0.78,
    "AED": 3.67,
    "SAR": 3.75,
    "INR": 83.90,
    "BDT": 117.20,
}

XMR_PRICE_USD = 160.00
MONERO_VAULT_ADDRESS = "47EhKrcAXhFLDcVV6YKipxgmTZHE3wk8vXHAGemK5h5VKkcWMszhyqrF3phn6pfNEvH1ooVja2mSzC17mqb5rN5QNvnveKK"


@dataclass
class GlobalBillingInvoice:
    invoice_id: str
    user_name: str
    user_email: str
    service_name: str
    local_currency: str
    local_price: float
    xmr_amount: float
    monero_address: str
    qr_code_uri: str
    status: str
    timestamp: float


class GlobalBillingEngine:
    """Manages global fiat-crypto exchange, billing emails, and QR settlements."""

    def __init__(self) -> None:
        self.cloud_mgr = CloudServicesManager()
        self.oauth_mgr = GmailOAuthManager()

    def convert_fiat_to_xmr(self, amount: float, currency: str = "USD") -> tuple[float, float]:
        """Convert local fiat currency to USD and Monero XMR equivalent."""
        curr = currency.upper()
        rate = FIAT_RATES_PER_USD.get(curr, 1.0)
        amount_usd = amount / rate
        xmr_amount = round(amount_usd / XMR_PRICE_USD, 6)
        return amount_usd, xmr_amount

    def generate_monero_qr_uri(self, address: str, amount_xmr: float, invoice_id: str) -> str:
        """Generate standard Monero wallet QR URI for 1-scan mobile payment."""
        params = {
            "tx_amount": f"{amount_xmr:.6f}",
            "tx_description": f"Sophyane Invoice {invoice_id}",
        }
        return f"monero:{address}?{urllib.parse.urlencode(params)}"

    def create_and_email_invoice(
        self,
        user_name: str,
        user_email: str,
        service_id: str,
        local_currency: str = "PKR",
        local_price: float = 2800.0,
    ) -> GlobalBillingInvoice:
        """Create global invoice, generate QR code URI, and dispatch billing email via badrpk@gmail.com."""
        inv_id = f"inv-nifdu-{int(time.time() * 1000) % 1000000}"
        amount_usd, xmr_amount = self.convert_fiat_to_xmr(local_price, local_currency)
        qr_uri = self.generate_monero_qr_uri(MONERO_VAULT_ADDRESS, xmr_amount, inv_id)

        svc = next((s for s in CLOUD_SERVICES_CATALOG if s.service_id == service_id), CLOUD_SERVICES_CATALOG[0])

        invoice = GlobalBillingInvoice(
            invoice_id=inv_id,
            user_name=user_name,
            user_email=user_email,
            service_name=svc.name,
            local_currency=local_currency,
            local_price=local_price,
            xmr_amount=xmr_amount,
            monero_address=MONERO_VAULT_ADDRESS,
            qr_code_uri=qr_uri,
            status="pending_payment",
            timestamp=time.time(),
        )

        # Dispatch Billing Email via badrpk@gmail.com
        html_content = f"""
        <div style="font-family: Arial, sans-serif; background-color: #090d16; color: #f8fafc; padding: 24px; border-radius: 16px;">
          <h2 style="color: #38bdf8;">Sophyane Global Cloud Invoice #{inv_id}</h2>
          <p>Hi <strong>{user_name}</strong> ({user_email}),</p>
          <p>Thank you for subscribing to <strong>{svc.name}</strong>.</p>

          <div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 12px; margin: 16px 0;">
            <p><strong>Service:</strong> {svc.name} ({svc.aws_equivalent})</p>
            <p><strong>Local Currency Bill:</strong> {local_price:.2f} {local_currency} (~${amount_usd:.2f} USD)</p>
            <p><strong>Monero Equivalent:</strong> <span style="color: #34d399; font-weight: bold;">{xmr_amount:.6f} XMR</span></p>
            <p><strong>Payment Vault Address:</strong><br><code>{MONERO_VAULT_ADDRESS}</code></p>
          </div>

          <p>Scan the Monero QR URI below with your crypto wallet to settle instantly:</p>
          <p><code>{qr_uri}</code></p>

          <hr style="border-color: rgba(255,255,255,0.1);">
          <p style="font-size: 0.8rem; color: #94a3b8;">Sent via Sophyane Global Engine from badrpk@gmail.com</p>
        </div>
        """

        try:
            send_email(
                to=user_email,
                subject=f"[Invoice #{inv_id}] Sophyane Cloud Service Bill ({local_price} {local_currency})",
                body=f"Sophyane Invoice #{inv_id} for {svc.name}. Amount: {xmr_amount:.6f} XMR. Vault: {MONERO_VAULT_ADDRESS}",
            )
        except Exception as err:
            print(f"Email Dispatch Note for {user_email}: {err}")

        return invoice

    def simulate_wallet_qr_scan_and_settle(self, invoice: GlobalBillingInvoice) -> dict[str, Any]:
        """Simulate mobile local wallet scanning QR code, broadcasting XMR tx, and provisioning service."""
        invoice.status = "paid_and_provisioned"
        return {
            "ok": True,
            "invoice_id": invoice.invoice_id,
            "user_email": invoice.user_email,
            "service_provisioned": invoice.service_name,
            "paid_amount_xmr": invoice.xmr_amount,
            "paid_local_amount": f"{invoice.local_price:.2f} {invoice.local_currency}",
            "settlement_status": "CONFIRMED_ON_CHAIN",
            "global_node_location": "Sophyane Cloud Node (154.57.212.38)",
        }
