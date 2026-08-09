"""Monzo Developer API Client for Sophyane."""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MONZO_API_BASE = "https://api.monzo.com"

class MonzoClient:
    def __init__(self, access_token: str | None = None) -> None:
        self.access_token = access_token or os.getenv("MONZO_ACCESS_TOKEN", "")
        if not self.access_token:
            env_file = Path.home() / ".config" / "sophyane" / "crypto.env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("MONZO_ACCESS_TOKEN="):
                        raw = line.split("=", 1)[1]
                        self.access_token = raw.replace('"', '').replace("'", '').strip()

    def is_configured(self) -> bool:
        return bool(self.access_token) and not self.access_token.startswith("access_token_00000")

    def whoami(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"authenticated": False, "error": "MONZO_ACCESS_TOKEN not set in ~/.config/sophyane/crypto.env"}

        url = f"{MONZO_API_BASE}/ping/whoami"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "Sophyane-Monzo-Engine/21.2.0"
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"authenticated": False, "error": str(e)}
