"""Verified per-workspace browser launcher.

This module has a distinct name so stale bytecode from older browser launchers cannot
intercept project previews.
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import shutil
import subprocess
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]
_SERVERS: dict[Path, tuple[http.server.ThreadingHTTPServer, threading.Thread, str]] = {}


def _server_for(workspace: Path) -> str:
    root = workspace.resolve()
    existing = _SERVERS.get(root)
    if existing and existing[1].is_alive():
        return existing[2]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True, name=f"sophyane-preview-{server.server_port}")
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    _SERVERS[root] = (server, thread, base)
    return base


def open_verified_browser(workspace: Path, progress: Progress) -> tuple[bool, str]:
    candidate = workspace.resolve() / "index.html"
    if not candidate.is_file():
        return False, "Browser launch blocked: index.html does not exist in the current workspace."
    expected = candidate.read_bytes()
    if len(expected) < 100:
        return False, "Browser launch blocked: index.html is empty or too small."

    base = _server_for(workspace)
    url = f"{base}/index.html?v={candidate.stat().st_mtime_ns}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except Exception as error:  # noqa: BLE001
        return False, f"Browser launch blocked: HTTP verification failed: {type(error).__name__}: {error}"

    expected_hash = hashlib.sha256(expected).hexdigest()
    actual_hash = hashlib.sha256(body).hexdigest()
    if status != 200 or actual_hash != expected_hash:
        return False, "Browser launch blocked: served page does not match current index.html."

    progress(f"Verified current workspace page over HTTP: {len(body)} bytes; SHA-256 {expected_hash[:12]}")
    progress(f"Opening verified browser preview: {url}")
    if shutil.which("termux-open-url"):
        completed = subprocess.run(["termux-open-url", url], text=True, capture_output=True)
        return completed.returncode == 0, (
            f"Browser file: {candidate}\nBrowser URL: {url}\n"
            f"HTTP verification: SHA-256 matched {expected_hash[:12]}\n"
            f"Browser command: termux-open-url {url}\nExit code: {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    if shutil.which("am"):
        completed = subprocess.run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url], text=True, capture_output=True)
        return completed.returncode == 0, (
            f"Browser file: {candidate}\nBrowser URL: {url}\n"
            f"HTTP verification: SHA-256 matched {expected_hash[:12]}\n"
            f"Browser command: am start ... {url}\nExit code: {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    opened = webbrowser.open(url)
    return bool(opened), f"Browser URL: {url}\nHTTP verification: SHA-256 matched {expected_hash[:12]}\nBrowser accepted={opened}."
