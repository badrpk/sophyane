"""Verified per-workspace browser launcher with trusted demo-photo localization."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]
_SERVERS: dict[Path, tuple[subprocess.Popen[bytes], str]] = {}
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
            request = urllib.request.Request(url, headers={"User-Agent": "Sophyane/21 premium-demo image fetcher"})
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


def _free_preview_port() -> int:
    """Choose an ephemeral loopback port for a detached preview server."""
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind(
            (
                "127.0.0.1",
                0,
            )
        )

        return int(
            sock.getsockname()[1]
        )


def _server_ready(
    base: str,
    *,
    timeout: float = 0.35,
) -> bool:
    try:
        with urllib.request.urlopen(
            f"{base}/index.html",
            timeout=timeout,
        ) as response:
            return (
                getattr(
                    response,
                    "status",
                    200,
                )
                == 200
            )
    except Exception:
        return False


def _wait_for_server(
    base: str,
    process: subprocess.Popen[bytes],
    *,
    timeout: float = 15.0,
) -> None:
    deadline = (
        time.monotonic()
        + timeout
    )

    last_error = ""

    while (
        time.monotonic()
        < deadline
    ):
        if (
            process.poll()
            is not None
        ):
            raise RuntimeError(
                "preview HTTP server exited "
                f"with code {process.returncode}"
            )

        try:
            with urllib.request.urlopen(
                f"{base}/index.html",
                timeout=1.0,
            ) as response:
                if (
                    getattr(
                        response,
                        "status",
                        200,
                    )
                    == 200
                ):
                    return

        except Exception as error:
            last_error = (
                f"{type(error).__name__}: "
                f"{error}"
            )

        time.sleep(
            0.05
        )

    raise RuntimeError(
        "preview HTTP server did not "
        "become ready"
        + (
            f": {last_error}"
            if last_error
            else ""
        )
    )


def _truthy_environment(
    name: str,
) -> bool:
    value = os.environ.get(
        name,
    )

    if value is None:
        return False

    return (
        value.strip().lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def _browser_preview_disabled() -> bool:
    """Return True when the current execution context forbids preview creation."""

    if any(
        _truthy_environment(name)
        for name in (
            "SOPHYANE_DISABLE_BROWSER_OPEN",
            "SOPHYANE_NO_AUTO_OPEN",
            "SOPHYANE_NO_BROWSER",
        )
    ):
        return True

    preview = os.environ.get(
        "SOPHYANE_BROWSER_PREVIEW"
    )

    if (
        preview is not None
        and preview.strip().lower()
        in {
            "0",
            "false",
            "no",
            "off",
        }
    ):
        return True

    return False


def _stop_process(
    process: subprocess.Popen[bytes],
    *,
    timeout: float = 2.0,
) -> None:
    """Stop one owned detached preview process without touching unrelated PIDs."""

    try:
        if process.poll() is not None:
            return
    except Exception:
        return

    try:
        process.terminate()
    except (
        OSError,
        ProcessLookupError,
    ):
        return
    except Exception:
        return

    try:
        process.wait(
            timeout=timeout,
        )
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return

    try:
        process.kill()
    except (
        OSError,
        ProcessLookupError,
    ):
        return
    except Exception:
        return

    try:
        process.wait(
            timeout=timeout,
        )
    except Exception:
        pass


def stop_preview_server(
    workspace: Path,
) -> bool:
    """Stop the detached preview owned for one exact workspace."""

    root = Path(
        workspace
    ).expanduser().resolve()

    existing = _SERVERS.pop(
        root,
        None,
    )

    if existing is None:
        return False

    process, _base = existing

    _stop_process(
        process
    )

    return True


def stop_all_preview_servers() -> int:
    """Stop only detached preview processes currently owned by this runtime."""

    roots = list(
        _SERVERS
    )

    stopped = 0

    for root in roots:
        if stop_preview_server(
            root
        ):
            stopped += 1

    return stopped


def _server_for(workspace: Path) -> str:
    """Return a preview URL whose server survives the caller process.

    Android VIEW/termux-open-url is asynchronous.  A daemon thread owned by
    the launching Python process can disappear before the external browser
    performs its first request.  The preview therefore runs as a detached
    Python HTTP-server process.
    """
    root = workspace.resolve()

    existing = _SERVERS.get(
        root
    )

    if existing:
        process, base = existing

        if (
            process.poll()
            is None
            and _server_ready(
                base
            )
        ):
            return base

        stop_preview_server(
            root
        )

    port = _free_preview_port()

    base = (
        "http://127.0.0.1:"
        f"{port}"
    )

    command = [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--bind",
        "127.0.0.1",
        "--directory",
        str(root),
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        _wait_for_server(
            base,
            process,
        )

    except Exception:
        _stop_process(
            process
        )

        raise

    _SERVERS[root] = (
        process,
        base,
    )

    return base


def _desktop_new_tab(url: str) -> tuple[bool, str]:
    """Open a URL in a distinct browser tab when a desktop browser is available."""
    browser_commands = (
        ("google-chrome", ["google-chrome", "--new-tab", url]),
        ("google-chrome-stable", ["google-chrome-stable", "--new-tab", url]),
        ("chromium", ["chromium", "--new-tab", url]),
        ("chromium-browser", ["chromium-browser", "--new-tab", url]),
        ("firefox", ["firefox", "--new-tab", url]),
    )
    for executable, command in browser_commands:
        if shutil.which(executable):
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError:
                continue
            return True, f"Browser command: {' '.join(command)}\nPID: {process.pid}"

    opened = webbrowser.open_new_tab(url)
    return bool(opened), f"Browser new-tab request accepted={opened}."


def open_verified_browser(workspace: Path, progress: Progress) -> tuple[bool, str]:
    candidate = workspace.resolve() / "index.html"

    if _browser_preview_disabled():
        return (
            False,
            "Browser preview suppressed by execution policy.",
        )

    if not candidate.is_file():
        return False, "Browser launch blocked: index.html does not exist in the current workspace."

    _localize_demo_photos(workspace, progress)
    expected = candidate.read_bytes()
    if len(expected) < 100:
        return False, "Browser launch blocked: index.html is empty or too small."

    base = _server_for(workspace)
    url = f"{base}/index.html?v={candidate.stat().st_mtime_ns}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except Exception as error:  # noqa: BLE001
        return False, f"Browser launch blocked: HTTP verification failed: {type(error).__name__}: {error}"

    expected_hash = hashlib.sha256(expected).hexdigest()
    actual_hash = hashlib.sha256(body).hexdigest()
    if status != 200 or actual_hash != expected_hash:
        return False, "Browser launch blocked: served page does not match current index.html."

    progress(f"Verified current workspace page over HTTP: {len(body)} bytes; SHA-256 {expected_hash[:12]}")

    try:
        from sophyane.rendered_evidence import (
            capture_rendered_evidence,
        )

        rendered = capture_rendered_evidence(
            url,
            workspace,
            progress,
        )

        rendered_summary = (
            rendered.summary()
        )

    except Exception as error:  # noqa: BLE001
        rendered_summary = (
            "Rendered evidence: unavailable: "
            f"{type(error).__name__}: {error}"
        )

        progress(
            rendered_summary
        )

    progress(f"Opening verified product preview in a new browser tab: {url}")

    if shutil.which("termux-open-url"):
        completed = subprocess.run(["termux-open-url", url], text=True, capture_output=True)
        return completed.returncode == 0, (
            f"Browser file: {candidate}\nBrowser URL: {url}\n"
            f"HTTP verification: SHA-256 matched {expected_hash[:12]}\n"
            f"{rendered_summary}\n"
            f"Browser command: termux-open-url {url}\nExit code: {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    if shutil.which("am"):
        completed = subprocess.run(
            [
                "am", "start", "--activity-new-task", "-a",
                "android.intent.action.VIEW", "-d", url,
            ],
            text=True,
            capture_output=True,
        )
        return completed.returncode == 0, (
            f"Browser file: {candidate}\nBrowser URL: {url}\n"
            f"HTTP verification: SHA-256 matched {expected_hash[:12]}\n"
            f"{rendered_summary}\n"
            f"Browser command: Android VIEW new-task {url}\nExit code: {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )

    opened, launch = _desktop_new_tab(url)
    return opened, (
        f"Browser file: {candidate}\nBrowser URL: {url}\n"
        f"HTTP verification: SHA-256 matched {expected_hash[:12]}\n"
        f"{rendered_summary}\n{launch}"
    )
