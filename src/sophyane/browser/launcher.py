"""Sophyane Browser — Chromium-based shell for the Sophyane home experience."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
BROWSER_PROFILE = STATE_DIR / "browser-profile"
BROWSER_HOME = Path(__file__).resolve().parent / "home"


CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "microsoft-edge",
    "msedge",
    # Flatpak ids handled separately
)


def find_chromium() -> str | None:
    env = os.environ.get("SOPHYANE_BROWSER") or os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for name in CHROMIUM_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    # macOS app bundle
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac).exists():
        return mac
    mac2 = "/Applications/Chromium.app/Contents/MacOS/Chromium"
    if Path(mac2).exists():
        return mac2
    return None


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def serve_browser_home(port: int | None = None) -> tuple[ThreadingHTTPServer, int, str]:
    """Serve the Sophyane Browser start page (static home UI)."""
    port = port or _free_port()
    home = BROWSER_HOME
    home.mkdir(parents=True, exist_ok=True)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(home), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/index.html"
    return server, port, url


def launch_sophyane_browser(
    *,
    open_home: bool = True,
    extra_args: list[str] | None = None,
    start_apis: bool = True,
) -> dict[str, Any]:
    """Launch Chromium (if available) with Sophyane profile + home page."""
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    server, port, home_url = serve_browser_home()

    api_threads: list[str] = []
    if start_apis:
        # Best-effort background mesh + hardware API for the browser UI.
        try:
            from sophyane.hardware_api import create_default_api, serve_hardware_api
            from sophyane.mesh.core import get_mesh_node

            api = create_default_api()
            hw = serve_hardware_api("127.0.0.1", 8770, api)
            threading.Thread(target=hw.serve_forever, daemon=True).start()
            api_threads.append("hardware-api:8770")
            node = get_mesh_node(8777)
            node.serve_background(host="127.0.0.1")
            api_threads.append("mesh:8777")
        except Exception as error:  # noqa: BLE001
            api_threads.append(f"api-error:{error}")

    chromium = find_chromium()
    launched: list[str] = []
    pid = None
    # SOPHYANE_BROWSER_MODE=tab forces new-tab in the user's default browser
    # (keeps flexibility even when Chromium is installed).
    force_tab = os.environ.get("SOPHYANE_BROWSER_MODE", "").lower() in {
        "tab",
        "new-tab",
        "webbrowser",
        "default",
    }
    if chromium and open_home and not force_tab:
        args = [
            chromium,
            f"--user-data-dir={BROWSER_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--app={home_url}",
            "--new-window",
        ]
        if extra_args:
            args.extend(extra_args)
        # On constrained containers allow no-sandbox when needed
        if os.environ.get("SOPHYANE_BROWSER_NO_SANDBOX", "").lower() in {"1", "true", "yes"}:
            args.append("--no-sandbox")
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid = proc.pid
            launched.append(f"chromium:{chromium}")
        except Exception as error:  # noqa: BLE001
            launched.append(f"chromium-failed:{error}")
            webbrowser.open(home_url, new=2)  # new tab when possible
            launched.append("webbrowser-new-tab-fallback")
    else:
        # Always preserve open-in-user-browser (new tab) path
        webbrowser.open(home_url, new=2)
        launched.append("webbrowser-new-tab")
        if force_tab:
            launched.append("mode-forced-tab")
        if not chromium:
            launched.append("chromium-not-found")

    return {
        "ok": True,
        "version": __version__,
        "home_url": home_url,
        "home_port": port,
        "profile": str(BROWSER_PROFILE),
        "chromium": chromium,
        "pid": pid,
        "launched": launched,
        "apis": api_threads,
        "modes": {
            "download_install": "sophyane-browser / sophyane --browser (Chromium profile when available)",
            "new_tab": "Default browser new tab (always available; SOPHYANE_BROWSER_MODE=tab to force)",
            "web_download": "/browser.html on cloud portal",
            "web_open_tab": "/browser-home/ on cloud portal (target=_blank)",
        },
        "note": (
            "Sophyane Browser uses system Chromium/Chrome when installed for a dedicated shell; "
            "opening the home UI in a new tab of the user's default browser remains intact "
            "(fallback and SOPHYANE_BROWSER_MODE=tab)."
        ),
    }


def main() -> int:
    """Console entry: sophyane-browser"""
    import json
    import sys

    result = launch_sophyane_browser(open_home=True, start_apis=True)
    print(json.dumps(result, indent=2))
    if not result.get("pid"):
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\nSophyane Browser stopped.", file=sys.stderr)
    return 0
