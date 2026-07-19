"""Runtime fixes for browser demos and safe multi-part file generation."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


def install_browser_patch() -> None:
    from sophyane import execution_runtime as runtime

    original_execute = runtime.execute_action
    written: set[tuple[str, str]] = set()

    def choose_html(workspace: Path, requested: str) -> Path | None:
        requested = requested.strip()
        if requested:
            parsed = urlparse(requested)
            if parsed.scheme in {"http", "https"}:
                return None
            raw = parsed.path if parsed.scheme == "file" else requested
            candidate = (workspace / raw.lstrip("/")).resolve()
            root = workspace.resolve()
            if candidate != root and root not in candidate.parents:
                return None
            if candidate.is_file() and candidate.suffix.lower() in {".html", ".htm"}:
                return candidate
        index = workspace / "index.html"
        if index.is_file():
            return index
        html_files = sorted(
            [*workspace.glob("*.html"), *workspace.glob("*.htm")],
            key=lambda path: (path.name != "index.html", path.name),
        )
        return html_files[0] if html_files else None

    def open_browser(workspace: Path, url: str, progress: Any) -> str:
        workspace = workspace.resolve()
        requested = url.strip()
        parsed = urlparse(requested) if requested else None
        if requested and parsed and parsed.scheme in {"http", "https"}:
            launch_url = requested
            target = None
        else:
            target = choose_html(workspace, requested)
            if target is None:
                files = ", ".join(path.name for path in sorted(workspace.iterdir()) if path.is_file()) or "none"
                return f"Browser launch blocked: no HTML file found in the workspace. Files present: {files}."
            relative = target.relative_to(workspace).as_posix()
            subprocess.Popen(
                [os.environ.get("PYTHON", "python3"), "-m", "http.server", "8000", "--bind", "127.0.0.1"],
                cwd=workspace,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            launch_url = f"http://127.0.0.1:8000/{quote(relative)}"

        progress(f"Opening browser: {launch_url}")
        if shutil.which("termux-open-url"):
            completed = subprocess.run(["termux-open-url", launch_url], text=True, capture_output=True)
            return (
                f"Browser file: {target.name if target else launch_url}\n"
                f"Browser command: termux-open-url {launch_url}\n"
                f"Exit code: {completed.returncode}\n{completed.stdout}{completed.stderr}"
            )
        if shutil.which("am"):
            completed = subprocess.run(
                ["am", "start", "-a", "android.intent.action.VIEW", "-d", launch_url],
                text=True,
                capture_output=True,
            )
            return f"Browser command: am start ... {launch_url}\nExit code: {completed.returncode}\n{completed.stdout}{completed.stderr}"
        opened = webbrowser.open(launch_url)
        return f"Browser open requested for {launch_url}; accepted={opened}."

    def execute_action(action: dict[str, Any], workspace: Path, progress: Any) -> tuple[bool, str]:
        normalized = runtime._normalize_action(action) or action
        kind = str(normalized.get("type") or "").strip().lower()
        if kind == "write_file":
            path = str(normalized.get("path") or normalized.get("file") or "").strip()
            key = (str(workspace.resolve()), path)
            target = (workspace / path).resolve() if path else workspace
            if key in written or target.exists():
                return False, (
                    f"Repeated write_file blocked for {path}. The file already exists. "
                    "Use append_file for the next chunk, or set replace=true only when intentionally replacing the complete file."
                )
            written.add(key)
        elif kind == "append_file":
            path = str(normalized.get("path") or normalized.get("file") or "").strip()
            written.add((str(workspace.resolve()), path))
        if kind in {"open_browser", "browser"}:
            result = open_browser(workspace, str(normalized.get("url") or normalized.get("path") or ""), progress)
            return (not result.startswith("Browser launch blocked")), result
        return original_execute(normalized, workspace, progress)

    runtime._open_browser = open_browser
    runtime.execute_action = execute_action
