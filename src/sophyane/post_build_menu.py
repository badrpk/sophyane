"""Interactive, evidence-based actions shown after a successful project build."""
from __future__ import annotations

import http.server
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

MENU = """╭────────────────────────────────────────╮
│ ✅ Project completed successfully      │
├────────────────────────────────────────┤
│ 1. Open in browser                     │
│ 2. Open project Bash shell             │
│ 3. Create app icon on this device      │
│ 4. Run or restart the project          │
│ 5. Edit or improve the project         │
│ 6. Show project files                  │
│ 7. Show URL, path, port, and status    │
│ 8. Package or export the project       │
│ 9. Start a new project                 │
│ 0. Exit and return to Sophyane         │
╰────────────────────────────────────────╯"""

ALIASES = {
    "browser": "1", "open": "1", "shell": "2", "bash": "2",
    "icon": "3", "run": "4", "restart": "4", "edit": "5",
    "improve": "5", "files": "6", "status": "7", "export": "8",
    "package": "8", "new": "9", "exit": "0", "quit": "0",
}


def normalize_choice(value: str) -> str | None:
    cleaned = value.strip().lower()
    if cleaned == "":
        return "1"
    cleaned = ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in set("0123456789") else None


def render_menu() -> str:
    return MENU + "\nPress Enter to open in browser, or choose [0-9]:"


def detect_entry_file(workspace: Path) -> Path | None:
    """Return only a recognized, runnable project entry point.

    Never treat an arbitrary workspace file, log, validator, provider response,
    or temporary artifact as proof that the requested project was built.
    """
    workspace = Path(workspace)
    preferred = (
        "index.html",
        "main.html",
        "app.html",
        "start.html",
        "main.py",
        "app.py",
        "server.py",
        "main.js",
        "index.js",
    )
    for name in preferred:
        path = workspace / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


@dataclass(frozen=True)
class CompletionEvidence:
    complete: bool
    entry: Path | None
    project_type: str
    errors: tuple[str, ...]


def verify_completion(workspace: Path) -> CompletionEvidence:
    """Validate tangible project evidence before presenting success."""
    workspace = Path(workspace).resolve()
    errors: list[str] = []

    if not workspace.is_dir():
        return CompletionEvidence(
            complete=False,
            entry=None,
            project_type="unknown",
            errors=("Workspace directory does not exist.",),
        )

    entry = detect_entry_file(workspace)
    if entry is None:
        return CompletionEvidence(
            complete=False,
            entry=None,
            project_type="unknown",
            errors=(
                "No recognized project entry file was found.",
                "Expected index.html, main.html, app.html, start.html, "
                "main.py, app.py, server.py, main.js, or index.js.",
            ),
        )

    suffix = entry.suffix.lower()
    project_type = {
        ".html": "browser",
        ".py": "python",
        ".js": "javascript",
    }.get(suffix, "unknown")

    try:
        content = entry.read_text(encoding="utf-8", errors="ignore")
    except OSError as error:
        errors.append(f"Entry file could not be read: {error}")
        content = ""

    if not content.strip():
        errors.append("Entry file is empty.")

    if suffix == ".html":
        lowered = content.lower()
        if "<html" not in lowered:
            errors.append("HTML entry does not contain an <html> element.")
        if "<body" not in lowered:
            errors.append("HTML entry does not contain a <body> element.")
        if "</html>" not in lowered:
            errors.append("HTML entry is incomplete: missing </html>.")
    elif suffix == ".py":
        try:
            compile(content, str(entry), "exec")
        except SyntaxError as error:
            errors.append(
                f"Python entry has a syntax error at line "
                f"{error.lineno}: {error.msg}"
            )

    return CompletionEvidence(
        complete=not errors,
        entry=entry,
        project_type=project_type,
        errors=tuple(errors),
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class ProjectServer:
    workspace: Path
    port: int | None = None
    thread: threading.Thread | None = None
    httpd: http.server.ThreadingHTTPServer | None = None

    @property
    def url(self) -> str | None:
        entry = detect_entry_file(self.workspace)
        if self.port is None or entry is None or entry.suffix.lower() != ".html":
            return None
        return f"http://127.0.0.1:{self.port}/{entry.relative_to(self.workspace).as_posix()}"

    def healthy(self) -> bool:
        if not self.url:
            return False
        try:
            with urlopen(self.url, timeout=2) as response:
                return response.status == 200
        except (OSError, URLError):
            return False

    def start(self) -> str:
        if self.healthy():
            return self.url or ""
        entry = detect_entry_file(self.workspace)
        if entry is None or entry.suffix.lower() != ".html":
            raise RuntimeError("No HTML entry file was found.")
        self.port = _free_port()
        handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(  # noqa: E731
            *args, directory=str(self.workspace), **kwargs
        )
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.healthy():
                return self.url or ""
            time.sleep(0.05)
        raise RuntimeError("Local server started but HTTP verification failed.")

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = None
        self.thread = None


class PostBuildMenu:
    """Phone-friendly project actions. Every success message follows verification."""

    def __init__(
        self,
        workspace: Path,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.input = input_fn
        self.output = output_fn
        self.server = ProjectServer(self.workspace)

    def completion_evidence(self) -> CompletionEvidence:
        return verify_completion(self.workspace)

    def available(self) -> bool:
        return self.completion_evidence().complete

    def run(self) -> str:
        if not sys.stdin.isatty():
            return "skip"

        evidence = self.completion_evidence()
        if not evidence.complete:
            self.output("\n❌ Project completion validation failed.")
            for error in evidence.errors:
                self.output(f"- {error}")
            self.output(
                "Success menu withheld. Continue the generation or repair cycle."
            )
            return "incomplete"

        while True:
            self.output("\n" + render_menu())
            try:
                choice = normalize_choice(self.input("Choose: "))
            except (EOFError, KeyboardInterrupt):
                self.output("")
                return "exit"
            if choice is None:
                self.output("Please choose a number from 0 to 9.")
                continue
            if choice == "0":
                return "exit"
            if choice == "9":
                self.output("Current project preserved. Use /new at the Sophyane prompt.")
                return "new"
            self._dispatch(choice)

    def _dispatch(self, choice: str) -> None:
        actions = {
            "1": self.open_browser, "2": self.open_shell, "3": self.create_icon,
            "4": self.run_project, "5": self.edit_project, "6": self.show_files,
            "7": self.show_status, "8": self.export_project,
        }
        try:
            actions[choice]()
        except Exception as error:  # noqa: BLE001
            self.output(f"Action failed: {error}")

    def open_browser(self) -> None:
        url = self.server.start()
        command = None
        if shutil.which("termux-open-url"):
            command = ["termux-open-url", url]
        elif platform.system() == "Darwin" and shutil.which("open"):
            command = ["open", url]
        elif platform.system() == "Windows":
            command = ["cmd", "/c", "start", "", url]
        elif shutil.which("xdg-open"):
            command = ["xdg-open", url]
        if command is None:
            raise RuntimeError(f"No browser launcher found. Open {url}")
        result = subprocess.run(command, check=False)
        if result.returncode != 0 or not self.server.healthy():
            raise RuntimeError("Browser command or HTTP verification failed.")
        self.output(f"Opened verified browser project: {url}")

    def open_shell(self) -> None:
        shell = shutil.which("bash") or os.environ.get("SHELL")
        if not shell:
            raise RuntimeError("No Bash-compatible shell was found.")
        subprocess.run([shell], cwd=self.workspace, check=False)
        self.output(f"Returned from shell: {self.workspace}")

    def create_icon(self) -> None:
        entry = detect_entry_file(self.workspace)
        if entry is None or entry.suffix.lower() != ".html":
            raise RuntimeError("App icon setup currently requires an HTML project.")
        name = self.input("App name [Sophyane App]: ").strip() or "Sophyane App"
        manifest = self.workspace / "manifest.json"
        service_worker = self.workspace / "service-worker.js"
        manifest.write_text(json.dumps({
            "name": name, "short_name": name[:12], "start_url": "./",
            "display": "standalone", "background_color": "#ffffff",
            "theme_color": "#2563eb", "icons": []
        }, indent=2) + "\n", encoding="utf-8")
        service_worker.write_text(
            "self.addEventListener('install',e=>self.skipWaiting());\n"
            "self.addEventListener('fetch',()=>{});\n", encoding="utf-8"
        )
        html = entry.read_text(encoding="utf-8")
        if 'rel="manifest"' not in html and "rel='manifest'" not in html:
            marker = "<link rel=\"manifest\" href=\"manifest.json\">"
            html = html.replace("</head>", marker + "\n</head>") if "</head>" in html else marker + html
            entry.write_text(html, encoding="utf-8")
        if not manifest.is_file() or not service_worker.is_file():
            raise RuntimeError("PWA files could not be verified.")
        self.output("Installable PWA metadata created. In the browser, choose ‘Add to Home screen’ and confirm.")

    def run_project(self) -> None:
        entry = detect_entry_file(self.workspace)
        if entry is None:
            raise RuntimeError("No project entry file found.")
        if entry.suffix.lower() == ".html":
            url = self.server.start()
            self.output(f"Running: {url} (HTTP 200 verified)")
            return
        commands = {
            ".py": [sys.executable, entry.name],
            ".js": [shutil.which("node") or "node", entry.name],
            ".sh": [shutil.which("bash") or "bash", entry.name],
        }
        command = commands.get(entry.suffix.lower())
        if command is None:
            raise RuntimeError(f"Unsupported entry type: {entry.suffix}")
        result = subprocess.run(command, cwd=self.workspace, check=False)
        self.output(f"Process finished with exit code {result.returncode}.")

    def edit_project(self) -> None:
        request = self.input("Describe the change: ").strip()
        if request:
            self.output(f"Return to Sophyane and enter: {request}")
        else:
            self.output("No change requested.")

    def show_files(self) -> None:
        files = sorted(path for path in self.workspace.rglob("*") if path.is_file())
        entry = detect_entry_file(self.workspace)
        self.output(f"Workspace: {self.workspace}")
        for path in files[:100]:
            label = " [entry]" if path == entry else ""
            self.output(f"- {path.relative_to(self.workspace)} ({path.stat().st_size} bytes){label}")

    def show_status(self) -> None:
        entry = detect_entry_file(self.workspace)
        newest = max((p.stat().st_mtime for p in self.workspace.rglob("*") if p.is_file()), default=0)
        self.output(f"Workspace: {self.workspace}")
        self.output(f"Main file: {entry or 'none'}")
        self.output(f"URL: {self.server.url or 'not running'}")
        self.output(f"HTTP status: {'200 OK' if self.server.healthy() else 'not verified'}")
        self.output(f"Last modified: {time.ctime(newest) if newest else 'unknown'}")

    def export_project(self) -> None:
        destination = self.workspace.parent / f"{self.workspace.name}.zip"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in self.workspace.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(self.workspace))
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("Export verification failed.")
        self.output(f"Exported verified ZIP: {destination} ({destination.stat().st_size} bytes)")
