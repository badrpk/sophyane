"""Sophyane Browser — Chromium-based shell for the Sophyane home experience."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from sophyane.version import __version__

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
BROWSER_PROFILE = STATE_DIR / "browser-profile"
NIFDU_BROWSER_PROFILE = STATE_DIR / "nifdu-browser-profile"
BROWSER_HOME = Path(__file__).resolve().parent / "home"

# SOPHYANE_NIFDU_TRACKED_BROWSER_LAUNCH_AUTHORITY_V1
NIFDU_CDP_HOST_DEFAULT = "127.0.0.1"
NIFDU_CDP_PORT_DEFAULT = 9222
NIFDU_CHATGPT_URL_DEFAULT = "https://chatgpt.com/"


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



def _nifdu_cdp_endpoint() -> tuple[str, int]:
    """Return the configured NIFDU Chromium CDP endpoint."""

    host = (
        os.environ.get(
            "SOPHYANE_CDP_HOST",
            NIFDU_CDP_HOST_DEFAULT,
        )
        .strip()
        or NIFDU_CDP_HOST_DEFAULT
    )

    raw_port = os.environ.get(
        "SOPHYANE_CDP_PORT",
        str(NIFDU_CDP_PORT_DEFAULT),
    )

    try:
        port = int(raw_port)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "SOPHYANE_CDP_PORT must be an integer"
        ) from error

    if not 1 <= port <= 65535:
        raise ValueError(
            "SOPHYANE_CDP_PORT must be between 1 and 65535"
        )

    return host, port


def _nifdu_cdp_ready(
    host: str,
    port: int,
    *,
    timeout: float = 0.5,
) -> bool:
    """Return True only for a responding Chromium DevTools endpoint."""

    url = (
        f"http://{host}:{port}"
        "/json/version"
    )

    try:
        with urllib.request.urlopen(
            url,
            timeout=timeout,
        ) as response:
            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )
    except Exception:  # noqa: BLE001
        return False

    browser = str(
        payload.get(
            "Browser",
            "",
        )
    ).lower()

    websocket_url = str(
        payload.get(
            "webSocketDebuggerUrl",
            "",
        )
    )

    return (
        (
            "chromium" in browser
            or "chrome" in browser
            or "headlesschrome" in browser
        )
        and websocket_url.startswith(
            "ws"
        )
    )


# SOPHYANE_NIFDU_CDP_STARTUP_READINESS_AUTHORITY_V1
def _wait_for_nifdu_cdp(
    process: subprocess.Popen[Any],
    host: str,
    port: int,
    *,
    timeout: float = 15.0,
    interval: float = 0.20,
) -> tuple[bool, str]:
    """Wait boundedly for the launched Chromium DevTools endpoint."""

    deadline = (
        time.monotonic()
        + max(
            0.1,
            float(timeout),
        )
    )

    while time.monotonic() < deadline:
        return_code = process.poll()

        if return_code is not None:
            return (
                False,
                (
                    "Chromium exited before CDP became ready "
                    f"with status {return_code}"
                ),
            )

        if _nifdu_cdp_ready(
            host,
            port,
        ):
            return (
                True,
                "",
            )

        time.sleep(
            max(
                0.01,
                float(interval),
            )
        )

    if _nifdu_cdp_ready(
        host,
        port,
    ):
        return (
            True,
            "",
        )

    return (
        False,
        (
            "Chromium CDP endpoint did not become ready at "
            f"{host}:{port} within {timeout:g} seconds"
        ),
    )


# SOPHYANE_NIFDU_TERMUX_X11_SOCKET_AUTHORITY_V1
def _detect_termux_x11_display() -> str | None:
    """Return :0 only when a concrete Termux:X11 X0 endpoint exists."""

    if (
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
    ):
        return None

    prefix = os.environ.get("PREFIX", "")
    if not prefix.startswith(
        "/data/data/com.termux/files/"
    ):
        return None

    tmpdir = os.environ.get("TMPDIR", "").strip()
    if not tmpdir:
        return None

    x0 = os.path.join(
        tmpdir,
        ".X11-unix",
        "X0",
    )

    if os.path.exists(x0):
        return ":0"

    return None


def launch_nifdu_browser(
    *,
    open_chatgpt: bool = True,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Ensure the tracked NIFDU Chromium/CDP browser is running.

    NIFDU owns a dedicated Chromium profile and CDP endpoint. If the
    configured DevTools endpoint is already live, it is reused instead
    of starting a second Chromium instance.
    """

    host, port = _nifdu_cdp_endpoint()

    if _nifdu_cdp_ready(
        host,
        port,
    ):
        return {
            "ok": True,
            "reused": True,
            "launched": False,
            "pid": None,
            "chromium": find_chromium(),
            "host": host,
            "port": port,
            "profile": str(
                NIFDU_BROWSER_PROFILE
            ),
            "headless": not bool(
                os.environ.get("DISPLAY")
                or os.environ.get("WAYLAND_DISPLAY")
            ),
        }

    chromium = find_chromium()

    if not chromium:
        return {
            "ok": False,
            "reused": False,
            "launched": False,
            "pid": None,
            "chromium": None,
            "host": host,
            "port": port,
            "profile": str(
                NIFDU_BROWSER_PROFILE
            ),
            "error": (
                "Chromium executable was not found."
            ),
        }

    NIFDU_BROWSER_PROFILE.mkdir(
        parents=True,
        exist_ok=True,
    )

    args = [
        chromium,
        (
            "--user-data-dir="
            f"{NIFDU_BROWSER_PROFILE}"
        ),
        (
            "--remote-debugging-address="
            f"{host}"
        ),
        (
            "--remote-debugging-port="
            f"{port}"
        ),
        # SOPHYANE_NIFDU_CDP_WEBSOCKET_ORIGIN_AUTHORITY_V1
        (
            "--remote-allow-origins="
            f"http://{host}:{port}"
        ),
        "--no-first-run",
        "--no-default-browser-check",
    ]

    # SOPHYANE_NIFDU_AUTO_HEADLESS_DISPLAY_AUTHORITY_V1
    #
    # NIFDU requires Chromium/CDP, not necessarily a visible window.
    # On Termux/Android there is commonly no X11/Wayland display.
    # In that environment GUI Chromium exits before CDP starts, so
    # use Chromium's native headless mode automatically.
    # SOPHYANE_NIFDU_EXPLICIT_DISPLAY_AUTHORITY_V1
    #
    # A Termux:X11 X0 socket can remain present even when the parent
    # process has no usable GUI display. Real Android evidence showed
    # that treating that socket alone as display authority can make
    # Chromium take the GUI path and exit before CDP becomes ready.
    #
    # Only an explicitly exported DISPLAY/WAYLAND_DISPLAY selects GUI
    # mode. Otherwise NIFDU uses the proven headless Chromium/CDP path.
    has_display = bool(
        os.environ.get(
            "DISPLAY"
        )
        or os.environ.get(
            "WAYLAND_DISPLAY"
        )
    )

    if has_display:
        args.append(
            "--new-window"
        )
    else:
        args.extend(
            [
                "--headless=new",
                "--disable-gpu",
            ]
        )

    # SOPHYANE_NIFDU_TERMUX_NETWORK_SERVICE_IN_PROCESS_V2
    #
    # Play-store Termux injects libtermux-exec through LD_PRELOAD.
    # A Chromium network-service child launched through /proc/self/exe
    # cannot load that library inside Android's restricted linker namespace.
    #
    # Historical mitigation used --single-process / --no-zygote. Live
    # Android evidence proved that configuration can make CDP briefly ready
    # and then terminate Chromium with SIGSEGV.
    #
    # Preserve normal Chromium renderer/zygote process isolation. Only keep
    # the network service inside the browser process. This eliminates the
    # failing /proc/self/exe network-service child while retaining a stable
    # multiprocess Chromium/CDP runtime.
    termux_exec_preload = (
        "libtermux-exec.so"
        in os.environ.get(
            "LD_PRELOAD",
            "",
        )
    )

    termux_prefix = (
        os.environ.get(
            "PREFIX",
            "",
        ).startswith(
            "/data/data/com.termux/files/"
        )
    )

    termux_network_service_in_process = (
        termux_exec_preload
        and termux_prefix
    )

    if termux_network_service_in_process:
        feature_flag = (
            "--enable-features="
            "NetworkServiceInProcess2"
        )

        if feature_flag not in args:
            args.append(
                feature_flag
            )

        if "--no-sandbox" not in args:
            args.append(
                "--no-sandbox"
            )

    if (
        os.environ.get(
            "SOPHYANE_BROWSER_NO_SANDBOX",
            "",
        ).lower()
        in {
            "1",
            "true",
            "yes",
        }
    ):
        args.append(
            "--no-sandbox"
        )

    if extra_args:
        args.extend(
            extra_args
        )

    if open_chatgpt:
        args.append(
            os.environ.get(
                "SOPHYANE_NIFDU_CHAT_URL",
                NIFDU_CHATGPT_URL_DEFAULT,
            )
        )

    try:
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "start_new_session": True,
        }

        process = subprocess.Popen(
            args,
            **popen_kwargs,
        )
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "reused": False,
            "launched": False,
            "pid": None,
            "chromium": chromium,
            "host": host,
            "port": port,
            "profile": str(
                NIFDU_BROWSER_PROFILE
            ),
            "error": str(error),
        }

    ready, readiness_error = (
        _wait_for_nifdu_cdp(
            process,
            host,
            port,
        )
    )

    if not ready:
        return {
            "ok": False,
            "reused": False,
            "launched": True,
            "pid": process.pid,
            "chromium": chromium,
            "host": host,
            "port": port,
            "profile": str(
                NIFDU_BROWSER_PROFILE
            ),
            "headless": not has_display,
            "argv": args,
            "error": readiness_error,
        }

    return {
        "ok": True,
        "reused": False,
        "launched": True,
        "pid": process.pid,
        "chromium": chromium,
        "host": host,
        "port": port,
        "profile": str(
            NIFDU_BROWSER_PROFILE
        ),
        "headless": not has_display,
        "argv": args,
        "cdp_ready": True,
    }


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
