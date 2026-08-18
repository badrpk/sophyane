"""Local Chrome DevTools Protocol control for Sophyane Browser.

This module intentionally uses only the local Chromium debugging endpoint. It is
not an access-control bypass layer: callers remain responsible for authorization,
site terms, authentication, and Neuron policy at privileged action boundaries.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class CDPError(RuntimeError):
    """Raised when the local CDP endpoint cannot satisfy a request."""


@dataclass(frozen=True)
class CDPEndpoint:
    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _assert_loopback(host: str) -> None:
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise CDPError(f"Could not resolve CDP host: {host}") from exc

    for family, _, _, _, sockaddr in addresses:
        if family == socket.AF_INET:
            address = sockaddr[0]
            if not address.startswith("127."):
                raise CDPError("CDP endpoint must be bound to loopback.")
        elif family == socket.AF_INET6:
            if sockaddr[0] != "::1":
                raise CDPError("CDP endpoint must be bound to loopback.")


def _json_get(url: str, timeout: float = 3.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as exc:
        raise CDPError(f"CDP endpoint unavailable: {url}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CDPError("CDP endpoint returned invalid JSON.") from exc


def browser_version(endpoint: CDPEndpoint) -> dict[str, Any]:
    _assert_loopback(endpoint.host)
    payload = _json_get(f"{endpoint.base_url}/json/version")
    if not isinstance(payload, dict):
        raise CDPError("Unexpected /json/version response.")
    return payload


def list_targets(endpoint: CDPEndpoint) -> list[dict[str, Any]]:
    _assert_loopback(endpoint.host)
    payload = _json_get(f"{endpoint.base_url}/json/list")
    if not isinstance(payload, list):
        raise CDPError("Unexpected /json/list response.")
    return [item for item in payload if isinstance(item, dict)]


def new_target(endpoint: CDPEndpoint, url: str = "about:blank") -> dict[str, Any]:
    """Create a page target using Chromium's local debugging HTTP helper."""
    _assert_loopback(endpoint.host)
    quoted = urllib.parse.quote(url, safe=":/?&=#%")
    request = urllib.request.Request(
        f"{endpoint.base_url}/json/new?{quoted}",
        method="PUT",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CDPError("Could not create CDP target.") from exc
    if not isinstance(payload, dict):
        raise CDPError("Unexpected target response.")
    return payload


def target_summary(endpoint: CDPEndpoint) -> dict[str, Any]:
    version = browser_version(endpoint)
    targets = list_targets(endpoint)
    return {
        "ok": True,
        "endpoint": endpoint.base_url,
        "browser": version.get("Browser", "unknown"),
        "protocol_version": version.get("Protocol-Version", "unknown"),
        "websocket_debugger_url": version.get("webSocketDebuggerUrl"),
        "targets": [
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "title": item.get("title"),
                "url": item.get("url"),
                "websocket_debugger_url": item.get("webSocketDebuggerUrl"),
            }
            for item in targets
        ],
    }
