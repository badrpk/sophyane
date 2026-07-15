"""Unified Hardware/Software API for Sophyane multi-language clients.

Python is native. C++ and JS clients call the same JSON contract over HTTP
or import this module when embedded via pybind/subprocess.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

from sophyane.edge_agent import EDGE_SYSTEM_PROMPT, build_edge_health, edge_chat
from sophyane.hardware_registry import (
    format_hardware_report,
    hardware_compatibility_report,
    recommended_backends,
)
from sophyane.kernel import boot_kernel
from sophyane.kernel.app_factory import create_app
from sophyane.kernel.erp import erp_query, list_erp_systems, probe_all_erp, probe_erp
from sophyane.platform_probe import format_platform_report, probe_platform
from sophyane.version import __version__


GenerateFn = Callable[[str, str], str]


class HardwareAPI:
    """In-process API used by CLI, web, and language bridges."""

    def __init__(self, generate: GenerateFn | None = None) -> None:
        self._generate = generate

    def set_generate(self, generate: GenerateFn) -> None:
        self._generate = generate

    def health(self) -> dict[str, Any]:
        platform = probe_platform()
        return {
            "ok": True,
            "sophyane": __version__,
            "api": "hardware/v1",
            "platform": platform.to_dict(),
            "edge": build_edge_health().to_dict(),
        }

    def platform(self) -> dict[str, Any]:
        return probe_platform().to_dict()

    def hardware(self) -> dict[str, Any]:
        return hardware_compatibility_report()

    def backends(self) -> dict[str, Any]:
        return {"backends": recommended_backends()}

    def software(self) -> dict[str, Any]:
        report = hardware_compatibility_report()
        return {"open_software": report.get("open_software", [])}

    def chat(self, message: str, *, edge: bool = False) -> dict[str, Any]:
        if not self._generate:
            return {
                "ok": False,
                "error": "No generator bound. Configure a provider or start local_gguf.",
            }
        if edge:
            text = edge_chat(message, self._generate)
        else:
            text = self._generate(
                message,
                "You are Sophyane. Answer briefly and accurately.",
            )
        return {"ok": True, "message": message, "reply": text, "edge": edge}

    def kernel(self) -> dict[str, Any]:
        return boot_kernel().status().to_dict()

    def create_app(self, params: dict[str, Any]) -> dict[str, Any]:
        return create_app(
            str(params.get("target") or "web"),
            str(params.get("name") or "SophyaneApp"),
            output_dir=params.get("output_dir"),
            description=str(params.get("description") or ""),
        ).to_dict()

    def erp(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        system = str(params.get("system") or "").strip()
        if system:
            return probe_erp(system).to_dict()
        return {"catalog": list_erp_systems(), "status": probe_all_erp()}

    def erp_call(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        return erp_query(
            str(params.get("system") or ""),
            str(params.get("path") or ""),
            method=str(params.get("method") or "GET"),
            body=params.get("body") if isinstance(params.get("body"), dict) else None,
        )

    def dispatch(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        table: dict[str, Callable[[], dict[str, Any]]] = {
            "health": self.health,
            "platform": self.platform,
            "hardware": self.hardware,
            "backends": self.backends,
            "software": self.software,
            "kernel": self.kernel,
        }
        if method == "chat":
            return self.chat(
                str(params.get("message") or params.get("prompt") or ""),
                edge=bool(params.get("edge")),
            )
        if method == "create_app":
            return {"ok": True, "result": self.create_app(params)}
        if method == "erp":
            return {"ok": True, "result": self.erp(params)}
        if method == "erp_query":
            return self.erp_call(params)
        if method == "report_text":
            return {
                "platform": format_platform_report(),
                "hardware": format_hardware_report(),
            }
        handler = table.get(method)
        if not handler:
            return {"ok": False, "error": f"unknown method: {method}"}
        try:
            return {"ok": True, "result": handler()}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "error": str(error)}


def create_default_api() -> HardwareAPI:
    """Bind generator from current Sophyane provider when possible."""
    api = HardwareAPI()
    try:
        from sophyane.config import load_config
        from sophyane.main import create_provider

        provider = create_provider(load_config())

        def generate(prompt: str, system: str) -> str:
            return provider.generate(prompt, system)

        api.set_generate(generate)
    except Exception:
        # Leave unbound; chat will return a clear error.
        pass
    return api


class _Handler(BaseHTTPRequestHandler):
    api: HardwareAPI

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        routes = {
            "/v1/hardware/health": "health",
            "/v1/hardware/platform": "platform",
            "/v1/hardware/compat": "hardware",
            "/v1/hardware/backends": "backends",
            "/v1/hardware/software": "software",
            "/v1/hardware/report": "report_text",
            "/v1/kernel": "kernel",
            "/v1/kernel/status": "kernel",
            "/v1/erp": "erp",
        }
        method = routes.get(path)
        if not method:
            self._send(404, {"ok": False, "error": "not found", "path": path})
            return
        self._send(200, self.api.dispatch(method))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            params = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "invalid json"})
            return
        if path in {"/v1/hardware/chat", "/v1/chat"}:
            self._send(200, self.api.dispatch("chat", params if isinstance(params, dict) else {}))
            return
        if path in {"/v1/apps/create", "/v1/kernel/create_app"}:
            self._send(200, self.api.dispatch("create_app", params if isinstance(params, dict) else {}))
            return
        if path in {"/v1/erp/query", "/v1/erp/call"}:
            self._send(200, self.api.dispatch("erp_query", params if isinstance(params, dict) else {}))
            return
        if path == "/v1/erp":
            self._send(200, self.api.dispatch("erp", params if isinstance(params, dict) else {}))
            return
        if path == "/v1/hardware/rpc":
            method = str((params or {}).get("method") or "")
            p = (params or {}).get("params") or {}
            self._send(200, self.api.dispatch(method, p if isinstance(p, dict) else {}))
            return
        self._send(404, {"ok": False, "error": "not found", "path": path})


def serve_hardware_api(
    host: str = "127.0.0.1",
    port: int = 8770,
    api: HardwareAPI | None = None,
) -> ThreadingHTTPServer:
    """Start threaded HTTP hardware API (blocks if serve_forever is called)."""
    handler = type("BoundHandler", (_Handler,), {"api": api or create_default_api()})
    server = ThreadingHTTPServer((host, port), handler)
    return server
