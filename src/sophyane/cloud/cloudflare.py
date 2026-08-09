"""Cloudflare DNS API and Zero-Trust Tunnel manager for Sophyane.

Supports:
  1) Cloudflare v4 REST API (DNS records: A, CNAME, MX, TXT).
  2) Cloudflare Quick & Named Tunnels (cloudflared) to route port 80/443 traffic to local Android/Termux ports (e.g. 8888).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


API_URL = "https://api.cloudflare.com/client/v4"
ENV_FILE = Path.home() / ".config" / "sophyane" / "cloudflare.env"


@dataclass
class CloudflareConfig:
    api_token: str
    account_id: str = ""
    email: str = ""

    @classmethod
    def from_env(cls, path: Path | None = None) -> "CloudflareConfig":
        env: dict[str, str] = {}
        p = path or ENV_FILE
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_EMAIL"):
            if os.environ.get(k):
                env[k] = os.environ[k].strip()
        token = env.get("CLOUDFLARE_API_TOKEN") or env.get("CF_API_TOKEN") or ""
        account_id = env.get("CLOUDFLARE_ACCOUNT_ID") or ""
        email = env.get("CLOUDFLARE_EMAIL") or ""
        return cls(api_token=token, account_id=account_id, email=email)


class CloudflareClient:
    def __init__(self, config: CloudflareConfig | None = None) -> None:
        self.config = config or CloudflareConfig.from_env()

    def _headers(self) -> dict[str, str]:
        if not self.config.api_token:
            raise RuntimeError("Cloudflare API token missing. Set CLOUDFLARE_API_TOKEN in env or ~/.config/sophyane/cloudflare.env")
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API_URL}/{endpoint.lstrip('/')}"
        payload = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=payload, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("success"):
                    errors = result.get("errors", [])
                    raise RuntimeError(f"Cloudflare API error: {errors}")
                return result
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloudflare HTTP {e.code}: {err_body}")

    def list_zones(self) -> list[dict[str, Any]]:
        res = self._call("GET", "zones?per_page=50")
        return res.get("result", [])

    def get_zone_id(self, domain_name: str) -> str:
        zones = self.list_zones()
        clean = domain_name.casefold().strip().rstrip(".")
        for z in zones:
            if z.get("name", "").casefold() == clean:
                return z["id"]
        raise RuntimeError(f"Zone not found in Cloudflare for domain: {domain_name}")

    def list_dns_records(self, zone_id: str) -> list[dict[str, Any]]:
        res = self._call("GET", f"zones/{zone_id}/dns_records?per_page=100")
        return res.get("result", [])

    def create_dns_record(
        self,
        zone_id: str,
        name: str,
        record_type: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int = 10,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": record_type.upper(),
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied if record_type.upper() in {"A", "AAAA", "CNAME"} else False,
        }
        if record_type.upper() == "MX":
            data["priority"] = priority
        res = self._call("POST", f"zones/{zone_id}/dns_records", data=data)
        return res.get("result", {})


class CloudflareTunnel:
    """Manages cloudflared binary and zero-trust tunnels on Android/Linux."""

    @staticmethod
    def get_cloudflared_path() -> str | None:
        return shutil.which("cloudflared")

    @classmethod
    def is_installed(cls) -> bool:
        return cls.get_cloudflared_path() is not None

    @classmethod
    def start_quick_tunnel(cls, local_port: int = 8888, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        path = cls.get_cloudflared_path()
        if not path:
            return {
                "ok": False,
                "message": "cloudflared binary not installed. Run 'pkg install cloudflared' or install cloudflared.",
                "url": "",
            }
        cmd = [path, "tunnel", "--url", f"http://127.0.0.1:{local_port}"]
        if progress:
            progress(f"Starting Cloudflare Quick Tunnel for 127.0.0.1:{local_port}...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return {
            "ok": True,
            "message": f"Cloudflare tunnel process started (PID {proc.pid})",
            "pid": proc.pid,
            "local_port": local_port,
        }
