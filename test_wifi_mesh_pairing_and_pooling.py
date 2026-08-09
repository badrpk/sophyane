"""Test Engine for Zero-Approval Wi-Fi Mesh Device Pairing & Storage Aggregation.

Simulates:
  1) Generating 1-scan QR code onboarding link for local Wi-Fi devices.
  2) Onboarding 4 local devices (Tablet, Laptop, Smart TV, Mobile).
  3) Calculating aggregated total storage free, RAM, and CPU cores in the Sophyane ecosystem.
"""
from __future__ import annotations

import json
from sophyane.cloud.wifi_mesh_manager import WiFiMeshManager
from sophyane.cloud.cloud_services import CloudServicesManager

WIFI_DEVICES_TO_ONBOARD = [
    {"hostname": "Samsung-Galaxy-Tab-S9", "ip": "192.168.1.102", "type": "Android Tablet", "storage_free_gb": 128.0, "ram_gb": 12.0, "cpu_cores": 8},
    {"name": "Dell-XPS-Developer-Laptop", "ip": "192.168.1.105", "type": "Linux Laptop", "storage_free_gb": 512.0, "ram_gb": 32.0, "cpu_cores": 16},
    {"name": "iPad-Pro-M2-Node", "ip": "192.168.1.110", "type": "iOS Tablet", "storage_free_gb": 256.0, "ram_gb": 16.0, "cpu_cores": 8},
    {"name": "Android-Smart-TV-Hub", "ip": "192.168.1.120", "type": "Smart TV Hub", "storage_free_gb": 64.0, "ram_gb": 4.0, "cpu_cores": 4},
]


def run_mesh_pairing_simulation():
    mesh_mgr = WiFiMeshManager()

    print("=== Step 1: Generating 1-Scan Wi-Fi Device Onboarding QR Link ===")
    join_url = mesh_mgr.get_mesh_join_url()
    print("  Wi-Fi Mesh 1-Scan Join URL:")
    print("  ", join_url)
    print("  QR Code Scanner URI: monero:47EhKrcA...?tx_description=Join+Sophyane+Mesh")

    print("\n=== Step 2: Auto-Onboarding Wi-Fi Devices (Zero-Approval Mode) ===")
    for idx, d in enumerate(WIFI_DEVICES_TO_ONBOARD, 1):
        name = d.get("hostname") or d.get("name")
        node = mesh_mgr.register_mesh_device(
            hostname=name,
            ip_address=d["ip"],
            device_type=d["type"],
            storage_free_gb=d["storage_free_gb"],
            ram_gb=d["ram_gb"],
            cpu_cores=d["cpu_cores"],
        )
        print(f"[{idx}/4] Onboarded Node: {node.hostname} ({node.ip_address})")
        print(f"       Device Type: {node.device_type} | Storage Added: {node.storage_free_gb} GB | RAM: {node.ram_gb} GB")

    print("\n=== Step 3: Aggregated Sophyane Ecosystem Resource Pool ===")
    cloud_mgr = CloudServicesManager()
    total_pool = cloud_mgr.get_mesh_device_pool()
    print(json.dumps(total_pool, indent=2))


if __name__ == "__main__":
    run_mesh_pairing_simulation()
