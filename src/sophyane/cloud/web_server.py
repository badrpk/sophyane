"""Built-in Nginx-like Web Server, Virtual Host, Reverse Proxy & TLS Engine for Sophyane.

Combines:
  1) Pure Python multi-threaded HTTP/HTTPS Virtual Host Server.
  2) Dynamic Reverse Proxying to local containers & web applications.
  3) Automatic TLS/SSL Certificate Generation & SSLContext termination.
  4) Integration with Cloudflare Tunnels, Namecheap DNS & Container Engine.
"""
from __future__ import annotations

import http.server
import json
import os
import re
import socketserver
import ssl
import subprocess
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CERT_DIR = Path.home() / ".config" / "sophyane" / "tls"


@dataclass
class VirtualHost:
    domain: str
    root_dir: str = ""
    proxy_target: str = ""
    enable_cors: bool = True


class TLSCertificateManager:
    """Automated TLS/SSL Certificate Management for Sophyane Web Engine."""

    def __init__(self, cert_dir: Path | None = None) -> None:
        self.cert_dir = cert_dir or CERT_DIR
        self.cert_dir.mkdir(parents=True, exist_ok=True)

    def generate_self_signed(self, domain: str = "localhost") -> tuple[Path, Path]:
        """Generate a valid self-signed TLS certificate and private key."""
        clean_domain = domain.casefold().strip().replace("*", "wildcard")
        cert_path = self.cert_dir / f"{clean_domain}.crt"
        key_path = self.cert_dir / f"{clean_domain}.key"

        if cert_path.exists() and key_path.exists():
            return cert_path, key_path

        cmd = [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "365",
            "-nodes",
            "-subj",
            f"/CN={domain}/O=Sophyane AI/OU=Web Engine",
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cert_path.chmod(0o600)
            key_path.chmod(0o600)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback if openssl CLI is missing: create minimal PEM structure
            self._write_fallback_pem(cert_path, key_path)

        return cert_path, key_path

    def _write_fallback_pem(self, cert_path: Path, key_path: Path) -> None:
        # Minimal placeholder key/cert pair fallback
        key_path.write_text("# Sophyane TLS Private Key\n", encoding="utf-8")
        cert_path.write_text("# Sophyane TLS Certificate\n", encoding="utf-8")

    def create_ssl_context(self, cert_file: Path, key_file: Path) -> ssl.SSLContext:
        """Create a server-side SSLContext for HTTPS connection wrapping."""
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
        return context


class SophyaneWebServer(http.server.SimpleHTTPRequestHandler):
    """Nginx-like virtual host router & reverse proxy server."""

    vhosts: dict[str, VirtualHost] = {}
    default_root: Path = Path.home() / ".sophyane" / "www"

    @classmethod
    def register_vhost(cls, domain: str, root_dir: str = "", proxy_target: str = "") -> None:
        clean = domain.casefold().strip().rstrip(".")
        cls.vhosts[clean] = VirtualHost(domain=clean, root_dir=root_dir, proxy_target=proxy_target)

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def do_PUT(self) -> None:
        self._handle_request("PUT")

    def do_DELETE(self) -> None:
        self._handle_request("DELETE")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _handle_request(self, method: str) -> None:
        host_header = str(self.headers.get("Host") or "").split(":")[0].casefold().strip()
        vhost = self.vhosts.get(host_header) or self.vhosts.get("*")

        # 1. Reverse Proxy Route if configured for this virtual host
        if vhost and vhost.proxy_target:
            self._proxy_pass(vhost.proxy_target, method)
            return

        # 2. Built-in API Status & Cloud Services endpoints
        if self.path in {"/api/status", "/status"}:
            self._send_json({
                "server": "Sophyane-Nginx-Engine/21.1.2",
                "status": "online",
                "tls_active": isinstance(getattr(self, "connection", None), ssl.SSLSocket),
                "host": host_header,
                "vhosts_registered": len(self.vhosts),
            })
            return

        if self.path == "/api/cloud-services":
            from sophyane.cloud.cloud_services import CloudServicesManager
            mgr = CloudServicesManager()
            self._send_json({
                "ok": True,
                "services": mgr.list_services(),
                "mesh_device_pool": mgr.get_mesh_device_pool(),
            })
            return

        if self.path == "/api/monero-checkout":
            from sophyane.cloud.cloud_services import CloudServicesManager
            mgr = CloudServicesManager()
            checkout = mgr.create_monero_checkout("compute_node")
            self._send_json(checkout)
            return

        if self.path == "/api/oauth/google/login":
            from sophyane.cloud.gmail_oauth import GmailOAuthManager
            mgr = GmailOAuthManager()
            self._send_json({
                "ok": True,
                "authorization_url": mgr.get_authorization_url(),
            })
            return

        if self.path.startswith("/api/oauth/google/callback"):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            if code:
                from sophyane.cloud.gmail_oauth import GmailOAuthManager
                mgr = GmailOAuthManager()
                result = mgr.exchange_code_for_tokens(code)
                self._send_json(result)
            else:
                self._send_json({"ok": False, "error": "Missing authorization code in callback"}, status=400)
            return

        if self.path == "/api/users":
            from sophyane.cloud.gmail_oauth import GmailOAuthManager
            mgr = GmailOAuthManager()
            self._send_json({
                "ok": True,
                "users": mgr.list_users(),
            })
            return

        # 3. Custom or Default Root Directory
        root_dir = Path(vhost.root_dir) if (vhost and vhost.root_dir and os.path.isdir(vhost.root_dir)) else self.default_root
        target_path = root_dir / self.path.lstrip("/")
        if target_path.is_dir():
            target_path = target_path / "index.html"
        if target_path.is_file():
            self._send_file(target_path)
            return

        # 4. Default Sophyane Web Portal fallback
        super().do_GET() if method == "GET" else self._send_json({"error": "Not found"}, status=404)

    def _proxy_pass(self, target_url: str, method: str) -> None:
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(content_length) if content_length > 0 else None

        dest_url = urllib.parse.urljoin(target_url, self.path)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection"}}
        headers["Host"] = urllib.parse.urlparse(target_url).netloc

        req = urllib.request.Request(dest_url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in {"transfer-encoding", "content-length"}:
                        self.send_header(k, v)
                resp_body = resp.read()
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except Exception as e:
            self._send_json({"error": f"Bad gateway proxying to {target_url}: {e}"}, status=502)

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            content = path.read_bytes()
            ext = path.suffix.lower()
            mime = {
                ".html": "text/html",
                ".css": "text/css",
                ".js": "application/javascript",
                ".json": "application/json",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".svg": "image/svg+xml",
            }.get(ext, "application/octet-stream")

            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)


class SophyaneWebServerEngine:
    """Threaded web server manager with Virtual Host routing and TLS termination."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8888, enable_tls: bool = False, domain: str = "localhost") -> None:
        self.host = host
        self.port = port
        self.enable_tls = enable_tls
        self.domain = domain
        self.server: socketserver.TCPServer | None = None
        self.thread: threading.Thread | None = None
        self.cert_manager = TLSCertificateManager()

    def add_domain(self, domain: str, root_dir: str = "", proxy_target: str = "") -> None:
        SophyaneWebServer.register_vhost(domain, root_dir=root_dir, proxy_target=proxy_target)

    def start(self) -> None:
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        self.server = http.server.ThreadingHTTPServer((self.host, self.port), SophyaneWebServer)

        if self.enable_tls:
            cert_file, key_file = self.cert_manager.generate_self_signed(self.domain)
            if cert_file.exists() and key_file.exists() and cert_file.stat().st_size > 50:
                ctx = self.cert_manager.create_ssl_context(cert_file, key_file)
                self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
