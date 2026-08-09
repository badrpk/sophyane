"""Sophyane Cloud Services Suite & Distributed Device Mesh Engine.

Provides an AWS/Azure/GCP-grade local-first cloud architecture:
  1) Compute Cloud (Sophyane EC2/Lambda equivalent via mesh & local execution).
  2) Storage Cloud (Sophyane S3/EBS equivalent pooling local & Wi-Fi device disks).
  3) AI Inference Cloud (Gemini 3.6 Flash / Local GGUF / Federated Mesh cluster).
  4) Database Cloud (SQLite / PostgreSQL / Key-Value store).
  5) Mail Cloud (SMTP / IMAP / Webmail plane).
  6) Monero Payment Vault (Crypto billing & zero-knowledge invoice processing).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from sophyane.cloud.crypto_billing import load_crypto_env, create_invoice, get_invoice
from sophyane.mesh.discovery import discover_peers, _local_ips
from sophyane.mesh.federation import local_share_stats


STATE_DIR = Path.home() / ".local" / "state" / "sophyane" / "cloud_services"
SERVICES_DB = STATE_DIR / "services.db"


@dataclass
class ServiceSpec:
    service_id: str
    name: str
    category: str
    aws_equivalent: str
    description: str
    pricing_xmr: float
    status: str


CLOUD_SERVICES_CATALOG: list[ServiceSpec] = [
    ServiceSpec(
        service_id="compute_node",
        name="Sophyane Elastic Compute (SEC2)",
        category="Compute",
        aws_equivalent="Amazon EC2 / AWS Lambda",
        description="Distributed task & code execution across local phone & Wi-Fi mesh nodes",
        pricing_xmr=0.01,
        status="active",
    ),
    ServiceSpec(
        service_id="object_storage",
        name="Sophyane Unified Storage (S3)",
        category="Storage",
        aws_equivalent="Amazon S3 / Elastic Block Store",
        description="Pooled encrypted file & artifact storage across all connected Wi-Fi devices",
        pricing_xmr=0.005,
        status="active",
    ),
    ServiceSpec(
        service_id="ai_inference",
        name="Sophyane AI Inference Engine",
        category="AI / ML",
        aws_equivalent="Amazon Bedrock / SageMaker",
        description="High-speed LLM inference powered by Google Gemini 3.6 Flash & local GGUF models",
        pricing_xmr=0.02,
        status="active",
    ),
    ServiceSpec(
        service_id="database_service",
        name="Sophyane Managed Database (SDB)",
        category="Database",
        aws_equivalent="Amazon RDS / DynamoDB",
        description="High-availability SQLite & PostgreSQL durable data storage",
        pricing_xmr=0.008,
        status="active",
    ),
    ServiceSpec(
        service_id="mail_platform",
        name="Sophyane Enterprise Mail Cloud",
        category="Networking",
        aws_equivalent="Amazon SES / WorkMail",
        description="Self-hosted SMTP, IMAP & Webmail plane for sastisawari.com",
        pricing_xmr=0.015,
        status="active",
    ),
    ServiceSpec(
        service_id="dns_cloudflare",
        name="Sophyane DNS & Shield Gate",
        category="Security",
        aws_equivalent="Amazon Route 53 / Cloudflare Shield",
        description="Namecheap DNS API sync & Cloudflare Zero-Trust SSL tunnels",
        pricing_xmr=0.002,
        status="active",
    ),
]


class CloudServicesManager:
    """Manages Cloud Services, Pooled Devices, and Monero Crypto Payments."""

    def __init__(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(SERVICES_DB)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS service_subscriptions (
                    id TEXT PRIMARY KEY,
                    service_id TEXT,
                    user_email TEXT,
                    domain TEXT,
                    monero_address TEXT,
                    amount_xmr REAL,
                    status TEXT,
                    created_at REAL
                )
            """)
            con.commit()

    def get_mesh_device_pool(self) -> dict[str, Any]:
        """Aggregate total storage, memory, and compute of all connected Wi-Fi devices."""
        from sophyane.cloud.wifi_mesh_manager import WiFiMeshManager
        mesh = WiFiMeshManager()
        return mesh.get_total_pooled_resources()

    def list_services(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in CLOUD_SERVICES_CATALOG]

    def create_monero_checkout(self, service_id: str, user_email: str = "badrpk@gmail.com") -> dict[str, Any]:
        """Generate a Monero Vault invoice for cloud service usage."""
        spec = next((s for s in CLOUD_SERVICES_CATALOG if s.service_id == service_id), CLOUD_SERVICES_CATALOG[0])
        crypto_env = load_crypto_env()

        monero_address = crypto_env.get("MONERO_PRIMARY_ADDRESS") or crypto_env.get("MONERO_SUBADDRESS") or "47EhKrcAXhFLDcVV6YKipxgmTZHE3wk8vXHAGemK5h5VKkcWMszhyqrF3phn6pfNEvH1ooVja2mSzC17mqb5rN5QNvnveKK"

        # Create Monero invoice
        try:
            invoice = create_invoice(plan_id="dev", user_email=user_email)
        except Exception:
            invoice = {
                "invoice_id": f"inv-{int(time.time())}",
                "pay_address": monero_address,
                "xmr_amount": spec.pricing_xmr,
                "status": "created",
            }

        with sqlite3.connect(str(SERVICES_DB)) as con:
            con.execute(
                "INSERT OR REPLACE INTO service_subscriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    invoice.get("invoice_id", f"inv-{int(time.time())}"),
                    spec.service_id,
                    user_email,
                    "sastisawari.com",
                    monero_address,
                    spec.pricing_xmr,
                    "pending",
                    time.time(),
                )
            )
            con.commit()

        return {
            "ok": True,
            "service": asdict(spec),
            "monero_vault_address": monero_address,
            "amount_xmr": spec.pricing_xmr,
            "invoice": invoice,
            "merchant": "Badar Uzaman (badrpk@gmail.com)",
        }
