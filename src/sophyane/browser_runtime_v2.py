"""Verified per-workspace browser launcher with trusted demo-photo localization."""
from __future__ import annotations

import functools
import hashlib
import http.server
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]
_SERVERS: dict[Path, tuple[http.server.ThreadingHTTPServer, threading.Thread, str]] = {}
_REMOTE_IMG = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*)([\"'])(https://[^\"']+)(\2)", re.I)
_TRUSTED_IMAGE_HOSTS = {"images.unsplash.com", "images.pexels.com", "cdn.pixabay.com"}


def _localize_demo_photos(workspace: Path, progress: Progress) -> None:
    index = workspace.resolve() / "index.html"
    if not index.is_file():
        return
    html = index.read_text(encoding="utf-8")
    assets = workspace.resolve() / "assets" / "images"
    assets.mkdir(parents=True, exist_ok=True)
    localized = 0
    remembered: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        nonlocal localized
        prefix, quote, url, closing = match.groups()
        if url in remembered:
            return f"{prefix}{quote}{remembered[url]}{closing}"
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host not in _TRUSTED_IMAGE_HOSTS or localized >= 6:
            return match.group(0)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        target = assets / f"photo-{digest}.jpg"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Sophyane/20 premium-demo image fetcher"})
            with urllib.request.urlopen(request, timeout=15) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if not content_type.startswith("image/"):
                    return match.group(0)
                body = response.read(6 * 1024 * 1024 + 1)
            if not 1024 <= len(body) <= 6 * 1024 * 1024:
                return match.group(0)
            target.write_bytes(body)
            relative = target.relative_to(workspace).as_posix()
            remembered[url] = relative
            localized += 1
            progress(f"Downloaded premium demo photo: {relative} ({len(body)} bytes)")
            return f"{prefix}{quote}{relative}{closing}"
        except Exception as error:  # noqa: BLE001
            progress(f"Demo photo download skipped for {host}: {type(error).__name__}")
            return match.group(0)

    rewritten = _REMOTE_IMG.sub(replace, html)
    if rewritten != html:
        index.write_text(rewritten, encoding="utf-8")
        progress(f"Localized {localized} trusted internet photo(s) into the project")


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
    _localize_demo_photos(workspace, progress)
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
