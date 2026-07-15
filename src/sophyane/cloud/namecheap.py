"""Namecheap API client: list domains, pick longest expiry, set A/AAAA DNS."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

API_URL = "https://api.namecheap.com/xml.response"
SANDBOX_URL = "https://api.sandbox.namecheap.com/xml.response"
ENV_FILE = Path.home() / ".config" / "sophyane" / "namecheap.env"


@dataclass
class NamecheapConfig:
    api_user: str
    api_key: str
    username: str
    client_ip: str
    sandbox: bool = False

    @classmethod
    def from_env(cls, path: Path | None = None) -> "NamecheapConfig":
        env: dict[str, str] = {}
        # Load file first
        p = path or ENV_FILE
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        # Process env overrides
        for k in (
            "NAMECHEAP_API_USER",
            "NAMECHEAP_API_KEY",
            "NAMECHEAP_USERNAME",
            "NAMECHEAP_CLIENT_IP",
            "NAMECHEAP_SANDBOX",
            "STATIC_IPV4",
            "STATIC_IPV6",
        ):
            if os.environ.get(k):
                env[k] = os.environ[k].strip()
        api_user = env.get("NAMECHEAP_API_USER") or env.get("ApiUser") or ""
        api_key = env.get("NAMECHEAP_API_KEY") or env.get("ApiKey") or ""
        username = env.get("NAMECHEAP_USERNAME") or env.get("UserName") or api_user
        client_ip = env.get("NAMECHEAP_CLIENT_IP") or env.get("ClientIp") or ""
        sandbox = (env.get("NAMECHEAP_SANDBOX") or "").lower() in {"1", "true", "yes"}
        if not api_user or not api_key or not client_ip:
            raise RuntimeError(
                "Namecheap credentials missing. Create ~/.config/sophyane/namecheap.env with:\n"
                "NAMECHEAP_API_USER=...\nNAMECHEAP_API_KEY=...\nNAMECHEAP_USERNAME=...\n"
                "NAMECHEAP_CLIENT_IP=your.public.ip  # must be whitelisted in Namecheap API"
            )
        return cls(api_user=api_user, api_key=api_key, username=username, client_ip=client_ip, sandbox=sandbox)


def save_env(
    *,
    api_user: str,
    api_key: str,
    username: str,
    client_ip: str,
    static_ipv4: str = "",
    static_ipv6: str = "",
    sandbox: bool = False,
) -> Path:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(
        "\n".join(
            [
                f"NAMECHEAP_API_USER={api_user}",
                f"NAMECHEAP_API_KEY={api_key}",
                f"NAMECHEAP_USERNAME={username}",
                f"NAMECHEAP_CLIENT_IP={client_ip}",
                f"NAMECHEAP_SANDBOX={'1' if sandbox else '0'}",
                f"STATIC_IPV4={static_ipv4}",
                f"STATIC_IPV6={static_ipv6}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    return ENV_FILE


class NamecheapClient:
    def __init__(self, config: NamecheapConfig | None = None) -> None:
        self.config = config or NamecheapConfig.from_env()
        self.base = SANDBOX_URL if self.config.sandbox else API_URL

    def _call(self, command: str, **params: str) -> ET.Element:
        q = {
            "ApiUser": self.config.api_user,
            "ApiKey": self.config.api_key,
            "UserName": self.config.username,
            "ClientIp": self.config.client_ip,
            "Command": command,
        }
        q.update({k: v for k, v in params.items() if v is not None})
        url = self.base + "?" + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
        root = ET.fromstring(raw)
        status = root.attrib.get("Status")
        if status != "OK":
            errors = [e.text for e in root.findall(".//{*}Error") if e.text]
            raise RuntimeError(f"Namecheap {command} failed: {errors or raw[:500]!r}")
        return root

    def list_domains(self) -> list[dict[str, Any]]:
        root = self._call("namecheap.domains.getList", PageSize="100")
        domains: list[dict[str, Any]] = []
        for d in root.findall(".//{*}Domain"):
            name = d.attrib.get("Name") or d.attrib.get("Domain") or ""
            exp = d.attrib.get("Expires") or d.attrib.get("ExpiredDate") or ""
            domains.append(
                {
                    "name": name,
                    "expires": exp,
                    "is_expired": (d.attrib.get("IsExpired") or "").lower() == "true",
                    "is_locked": (d.attrib.get("IsLocked") or "").lower() == "true",
                    "auto_renew": (d.attrib.get("AutoRenew") or "").lower() == "true",
                    "raw": dict(d.attrib),
                }
            )
        return domains

    def longest_expiry_domain(self) -> dict[str, Any] | None:
        domains = [d for d in self.list_domains() if d.get("name") and not d.get("is_expired")]
        if not domains:
            return None

        def sort_key(d: dict[str, Any]) -> datetime:
            exp = d.get("expires") or "1970-01-01"
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(exp[:19], fmt)
                except ValueError:
                    continue
            return datetime(1970, 1, 1)

        domains.sort(key=sort_key, reverse=True)
        best = domains[0]
        best["expires_parsed"] = sort_key(best).isoformat()
        return best

    def set_hosts(
        self,
        domain: str,
        *,
        ipv4: str,
        ipv6: str = "",
        host: str = "@",
        www: bool = True,
    ) -> dict[str, Any]:
        """Point domain A (and optional AAAA) records at static IP(s)."""
        # SLD/TLD split for Namecheap (naive: last label is TLD — works for .com/.net/.org/.io)
        parts = domain.lower().split(".")
        if len(parts) < 2:
            raise ValueError(f"invalid domain: {domain}")
        sld, tld = parts[0], ".".join(parts[1:])
        # Namecheap setHosts replaces ALL hosts — include common essentials
        hosts: list[dict[str, str]] = []
        idx = 1

        def add(hostname: str, record_type: str, address: str, ttl: str = "300") -> None:
            nonlocal idx
            hosts.append(
                {
                    f"HostName{idx}": hostname,
                    f"RecordType{idx}": record_type,
                    f"Address{idx}": address,
                    f"TTL{idx}": ttl,
                }
            )
            idx += 1

        add(host if host != "@" else "@", "A", ipv4)
        if www:
            add("www", "A", ipv4)
        # subdomains useful for API/portal
        add("api", "A", ipv4)
        add("sophyane", "A", ipv4)
        if ipv6:
            add("@", "AAAA", ipv6)
            if www:
                add("www", "AAAA", ipv6)
        params: dict[str, str] = {"SLD": sld, "TLD": tld}
        for h in hosts:
            params.update(h)
        root = self._call("namecheap.domains.dns.setHosts", **params)
        return {
            "ok": True,
            "domain": domain,
            "ipv4": ipv4,
            "ipv6": ipv6 or None,
            "hosts_set": len(hosts),
            "command": "namecheap.domains.dns.setHosts",
            "note": "DNS may take a few minutes to propagate",
        }

    def setup_sophyane_site(
        self,
        *,
        ipv4: str,
        ipv6: str = "",
        prefer_domain: str = "",
    ) -> dict[str, Any]:
        if prefer_domain:
            domain = prefer_domain
            meta = {"name": domain, "source": "prefer"}
        else:
            best = self.longest_expiry_domain()
            if not best:
                raise RuntimeError("No active domains found in Namecheap account")
            domain = best["name"]
            meta = best
        dns = self.set_hosts(domain, ipv4=ipv4, ipv6=ipv6)
        return {
            "ok": True,
            "selected_domain": domain,
            "domain_meta": meta,
            "dns": dns,
            "urls": {
                "site": f"https://{domain}/",
                "www": f"https://www.{domain}/",
                "api": f"https://api.{domain}/api/v1/health",
                "sophyane_sub": f"https://sophyane.{domain}/",
            },
        }
