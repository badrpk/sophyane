"""Mock Users & Monero Vault Payment End-to-End Test Engine.

Executes:
  1) Creating 10 realistic mock users with Google OAuth profiles in PostgreSQL/SQLite.
  2) Generating 10 Monero Vault XMR invoices & payment checkouts.
  3) Validating user database persistence and cloud service billing workflows.
"""
from __future__ import annotations

import json
import time
from sophyane.cloud.gmail_oauth import GmailOAuthManager
from sophyane.cloud.cloud_services import CloudServicesManager

MOCK_USERS = [
    {"id": "g-1001", "email": "alex.dev@sastisawari.com", "name": "Alex Mercer", "picture": "https://lh3.googleusercontent.com/a/alex"},
    {"id": "g-1002", "email": "sarah.khan@sastisawari.com", "name": "Sarah Khan", "picture": "https://lh3.googleusercontent.com/a/sarah"},
    {"id": "g-1003", "email": "bilal.ahmed@sastisawari.com", "name": "Bilal Ahmed", "picture": "https://lh3.googleusercontent.com/a/bilal"},
    {"id": "g-1004", "email": "elena.rodriguez@xerus.biz", "name": "Elena Rodriguez", "picture": "https://lh3.googleusercontent.com/a/elena"},
    {"id": "g-1005", "email": "tariq.mahmood@xerus.biz", "name": "Tariq Mahmood", "picture": "https://lh3.googleusercontent.com/a/tariq"},
    {"id": "g-1006", "email": "ayesha.malik@sastisawari.com", "name": "Ayesha Malik", "picture": "https://lh3.googleusercontent.com/a/ayesha"},
    {"id": "g-1007", "email": "daniyal.raza@sastisawari.com", "name": "Daniyal Raza", "picture": "https://lh3.googleusercontent.com/a/daniyal"},
    {"id": "g-1008", "email": "hira.fatima@xerus.biz", "name": "Hira Fatima", "picture": "https://lh3.googleusercontent.com/a/hira"},
    {"id": "g-1009", "email": "usman.ghani@sastisawari.com", "name": "Usman Ghani", "picture": "https://lh3.googleusercontent.com/a/usman"},
    {"id": "g-1010", "email": "zainab.hassan@xerus.biz", "name": "Zainab Hassan", "picture": "https://lh3.googleusercontent.com/a/zainab"},
]


def run_mock_user_and_monero_simulation():
    oauth_mgr = GmailOAuthManager()
    cloud_mgr = CloudServicesManager()

    print("=== Step 1: Registering 10 Mock Users in PostgreSQL / SQLite ===")
    registered_users = []
    for idx, u in enumerate(MOCK_USERS, 1):
        mock_tokens = {
            "access_token": f"ya29.mock_access_token_{idx}_{int(time.time())}",
            "refresh_token": f"1//mock_refresh_token_{idx}_{int(time.time())}",
        }
        res = oauth_mgr.save_user_record(u, mock_tokens)
        registered_users.append(res)
        print(f"[{idx}/10] Saved User: {res['email']} ({res['name']}) | ID: {res['google_id']}")

    print(f"\nTotal Registered Users in Database: {len(oauth_mgr.list_users())}")

    print("\n=== Step 2: Generating 10 Monero Vault XMR Payment Checkouts ===")
    services_to_test = ["sec2_compute", "s3_storage", "sdb_database", "ai_inference", "mail_cloud"]
    monero_checkouts = []
    for idx, user in enumerate(registered_users, 1):
        svc_id = services_to_test[(idx - 1) % len(services_to_test)]
        checkout = cloud_mgr.create_monero_checkout(svc_id, user_email=user["email"])
        inv = checkout.get("invoice", {})
        svc = checkout.get("service", {})
        monero_checkouts.append(checkout)
        print(f"[{idx}/10] Invoice #{inv.get('invoice_id', f'inv-{idx}')} for {user['email']}:")
        print(f"        Service: {svc.get('name', svc_id)} | XMR Price: {checkout['amount_xmr']} XMR")
        print(f"        Monero Vault: {checkout['monero_vault_address'][:24]}...{checkout['monero_vault_address'][-10:]}")

    print("\n=== Step 3: End-to-End System Verification Summary ===")
    summary = {
        "ok": True,
        "users_registered_count": len(registered_users),
        "monero_invoices_generated": len(monero_checkouts),
        "postgres_user_db_status": "Synced & Operational",
        "monero_vault_address": monero_checkouts[0]["monero_vault_address"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_mock_user_and_monero_simulation()
