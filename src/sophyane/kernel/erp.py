"""ERP connectors for Oracle, SAP, and common enterprise systems.

These are **integration adapters** (REST/OData/RFC-style configs + safe probes).
They do not ship proprietary Oracle/SAP SDKs; they provide a uniform Sophyane
interface you can point at real ERP endpoints with credentials in env/secrets.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin


ERP_CATALOG: dict[str, dict[str, Any]] = {
    "oracle": {
        "name": "Oracle ERP / Fusion Cloud",
        "protocols": ["REST", "SOAP", "JDBC"],
        "default_env": ["ORACLE_ERP_BASE_URL", "ORACLE_ERP_USER", "ORACLE_ERP_PASSWORD", "ORACLE_ERP_TOKEN"],
        "sample_paths": ["/fscmRestApi/resources/latest/", "/hcmRestApi/resources/latest/"],
    },
    "sap": {
        "name": "SAP S/4HANA / SAP BTP",
        "protocols": ["OData", "RFC", "REST"],
        "default_env": ["SAP_ODATA_BASE_URL", "SAP_USER", "SAP_PASSWORD", "SAP_TOKEN"],
        "sample_paths": ["/sap/opu/odata/sap/", "/http/"],
    },
    "odoo": {
        "name": "Odoo ERP (open source)",
        "protocols": ["JSON-RPC", "REST"],
        "default_env": ["ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD", "ODOO_API_KEY"],
        "sample_paths": ["/jsonrpc", "/web/session/authenticate"],
    },
    "dynamics": {
        "name": "Microsoft Dynamics 365",
        "protocols": ["OData", "REST"],
        "default_env": ["DYNAMICS_BASE_URL", "DYNAMICS_TOKEN", "AZURE_CLIENT_ID"],
        "sample_paths": ["/api/data/v9.2/"],
    },
    "netsuite": {
        "name": "Oracle NetSuite",
        "protocols": ["REST", "SuiteTalk"],
        "default_env": ["NETSUITE_BASE_URL", "NETSUITE_TOKEN"],
        "sample_paths": ["/services/rest/record/v1/"],
    },
    "erpnext": {
        "name": "ERPNext (open source)",
        "protocols": ["REST"],
        "default_env": ["ERPNEXT_URL", "ERPNEXT_KEY", "ERPNEXT_SECRET"],
        "sample_paths": ["/api/resource/"],
    },
}


@dataclass
class ERPConnectorStatus:
    system: str
    name: str
    configured: bool
    reachable: bool
    base_url: str
    protocols: list[str] = field(default_factory=list)
    message: str = ""
    env_present: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _env_first(keys: list[str]) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def _base_url_for(system: str) -> str:
    mapping = {
        "oracle": ["ORACLE_ERP_BASE_URL", "ORACLE_BASE_URL"],
        "sap": ["SAP_ODATA_BASE_URL", "SAP_BASE_URL"],
        "odoo": ["ODOO_URL", "ODOO_BASE_URL"],
        "dynamics": ["DYNAMICS_BASE_URL", "MSDYN_BASE_URL"],
        "netsuite": ["NETSUITE_BASE_URL"],
        "erpnext": ["ERPNEXT_URL"],
    }
    return _env_first(mapping.get(system, []))


def _token_for(system: str) -> str:
    mapping = {
        "oracle": ["ORACLE_ERP_TOKEN", "ORACLE_TOKEN"],
        "sap": ["SAP_TOKEN", "SAP_ODATA_TOKEN"],
        "odoo": ["ODOO_API_KEY", "ODOO_TOKEN"],
        "dynamics": ["DYNAMICS_TOKEN", "AZURE_ACCESS_TOKEN"],
        "netsuite": ["NETSUITE_TOKEN"],
        "erpnext": ["ERPNEXT_KEY"],
    }
    return _env_first(mapping.get(system, []))


def probe_erp(system: str, *, timeout: float = 5.0) -> ERPConnectorStatus:
    system = system.lower().strip()
    meta = ERP_CATALOG.get(system)
    if not meta:
        return ERPConnectorStatus(
            system=system,
            name=system,
            configured=False,
            reachable=False,
            base_url="",
            message=f"Unknown ERP system. Known: {', '.join(sorted(ERP_CATALOG))}",
        )

    env_present = [k for k in meta.get("default_env", []) if os.environ.get(k)]
    base = _base_url_for(system)
    token = _token_for(system)
    configured = bool(base) or bool(env_present)
    reachable = False
    message = "Not configured (set base URL env vars)"
    if base:
        message = "Configured; probing…"
        try:
            req = urllib.request.Request(base, method="GET")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            req.add_header("User-Agent", "Sophyane-ERP-Connector/16.4")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                reachable = 200 <= response.status < 500
                message = f"HTTP {response.status}"
        except urllib.error.HTTPError as error:
            # Auth challenges still prove reachability of the endpoint.
            reachable = error.code in {401, 403, 404, 405}
            message = f"HTTP {error.code} (endpoint responded)"
        except Exception as error:  # noqa: BLE001
            reachable = False
            message = f"Unreachable: {error}"

    return ERPConnectorStatus(
        system=system,
        name=str(meta["name"]),
        configured=configured,
        reachable=reachable,
        base_url=base,
        protocols=list(meta.get("protocols") or []),
        message=message,
        env_present=env_present,
    )


def list_erp_systems() -> list[dict[str, Any]]:
    return [
        {"id": key, "name": val["name"], "protocols": val["protocols"], "env": val["default_env"]}
        for key, val in ERP_CATALOG.items()
    ]


def probe_all_erp() -> list[dict[str, Any]]:
    return [probe_erp(system).to_dict() for system in ERP_CATALOG]


def erp_query(
    system: str,
    path: str = "",
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Generic REST/OData-style call against a configured ERP base URL."""
    status = probe_erp(system, timeout=min(timeout, 5.0))
    if not status.base_url:
        return {
            "ok": False,
            "error": "ERP base URL not configured",
            "system": system,
            "hint": ERP_CATALOG.get(system, {}).get("default_env", []),
        }
    url = urljoin(status.base_url.rstrip("/") + "/", (path or "").lstrip("/"))
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    token = _token_for(system)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw[:4000]}
            return {"ok": True, "status": response.status, "url": url, "data": parsed}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": error.code, "url": url, "error": raw[:2000]}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "url": url, "error": str(error)}
