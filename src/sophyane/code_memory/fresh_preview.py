"""Verified no-cache browser preview for one exact Sophyane workspace."""
from __future__ import annotations

import hashlib
import http.server
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
import webbrowser

from functools import partial
from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]

_LOCK = threading.RLock()
_ACTIVE_SERVER: http.server.ThreadingHTTPServer | None = None
_ACTIVE_THREAD: threading.Thread | None = None
_ACTIVE_WORKSPACE: Path | None = None
_ACTIVE_URL: str | None = None


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve files without allowing browser or proxy caching."""

    server_version = "SophyaneFreshPreview/1.0"

    def end_headers(self) -> None:
        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Clear-Site-Data", '"cache"')
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(
        self,
        format_string: str,
        *arguments,
    ) -> None:
        # Avoid noisy preview-server logs in the TUI.
        return


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def _available_port() -> int:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def stop_preview() -> None:
    global _ACTIVE_SERVER
    global _ACTIVE_THREAD
    global _ACTIVE_WORKSPACE
    global _ACTIVE_URL

    with _LOCK:
        server = _ACTIVE_SERVER
        thread = _ACTIVE_THREAD

        _ACTIVE_SERVER = None
        _ACTIVE_THREAD = None
        _ACTIVE_WORKSPACE = None
        _ACTIVE_URL = None

    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass

        try:
            server.server_close()
        except Exception:
            pass

    if (
        thread is not None
        and thread.is_alive()
        and thread is not threading.current_thread()
    ):
        thread.join(timeout=2)


def _open_url(url: str) -> None:
    # WSL: open explicitly in Windows.
    if (
        os.environ.get("WSL_DISTRO_NAME")
        or "microsoft" in os.uname().release.lower()
    ):
        try:
            result = subprocess.run(
                [
                    "cmd.exe",
                    "/c",
                    "start",
                    "",
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )

            if result.returncode == 0:
                return

        except Exception:
            pass

    webbrowser.open_new_tab(url)


def preview_workspace(
    workspace: Path,
    *,
    progress: Progress | None = None,
    open_browser: bool = True,
) -> str:
    """Serve and open only workspace/index.html after hash verification."""

    global _ACTIVE_SERVER
    global _ACTIVE_THREAD
    global _ACTIVE_WORKSPACE
    global _ACTIVE_URL

    progress = progress or (
        lambda _message: None
    )

    workspace = Path(workspace).expanduser().resolve()
    artifact = workspace / "index.html"

    if not workspace.is_dir():
        return (
            "Fresh preview refused: workspace does not exist: "
            + str(workspace)
        )

    if not artifact.is_file():
        return (
            "Fresh preview refused: no index.html in exact workspace: "
            + str(workspace)
        )

    if artifact.stat().st_size <= 0:
        return "Fresh preview refused: index.html is empty."

    expected_hash = _sha256(artifact)
    nonce = secrets.token_urlsafe(12)

    stop_preview()

    port = _available_port()

    handler = partial(
        NoCacheHandler,
        directory=str(workspace),
    )

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port),
        handler,
    )

    server.daemon_threads = True

    thread = threading.Thread(
        target=server.serve_forever,
        name="sophyane-fresh-preview",
        daemon=True,
    )

    thread.start()

    base_url = (
        f"http://127.0.0.1:{port}/index.html"
    )

    url = (
        f"{base_url}"
        f"?artifact={expected_hash}"
        f"&nonce={nonce}"
        f"&ts={time.time_ns()}"
    )

    # Confirm that the server is returning the exact file being previewed.
    served = None
    last_error = None

    for _attempt in range(30):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "Pragma": "no-cache",
                    "User-Agent": "SophyanePreviewVerifier/1.0",
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=3,
            ) as response:
                served = response.read()

            break

        except Exception as error:
            last_error = error
            time.sleep(0.1)

    if served is None:
        server.shutdown()
        server.server_close()

        return (
            "Fresh preview failed HTTP verification: "
            f"{type(last_error).__name__}: {last_error}"
        )

    served_hash = hashlib.sha256(
        served
    ).hexdigest()

    if served_hash != expected_hash:
        server.shutdown()
        server.server_close()

        return (
            "Fresh preview refused: served SHA-256 did not match "
            "the exact workspace artifact."
        )

    with _LOCK:
        _ACTIVE_SERVER = server
        _ACTIVE_THREAD = thread
        _ACTIVE_WORKSPACE = workspace
        _ACTIVE_URL = url

    progress(
        "Fresh preview verified: "
        f"{artifact.stat().st_size} bytes; "
        f"SHA-256 {expected_hash[:16]}; "
        f"workspace={workspace}"
    )

    if open_browser:
        _open_url(url)

    return "\n".join(
        [
            "Fresh browser preview opened.",
            f"Workspace: {workspace}",
            f"Artifact: {artifact}",
            f"SHA-256: {expected_hash}",
            f"URL: {url}",
            "Cache policy: no-store",
        ]
    )


def active_preview() -> dict[str, str | None]:
    with _LOCK:
        return {
            "workspace": (
                str(_ACTIVE_WORKSPACE)
                if _ACTIVE_WORKSPACE
                else None
            ),
            "url": _ACTIVE_URL,
        }


__all__ = [
    "active_preview",
    "preview_workspace",
    "stop_preview",
]
