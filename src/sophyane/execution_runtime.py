"""Observable bounded execution loop for structured software actions."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]


def coding_request_needs_language(message: str) -> bool:
    text = message.lower()
    coding = any(word in text for word in (
        "build", "make", "create", "develop", "game", "app", "website", "api", "script", "program"
    ))
    explicit = any(word in text for word in (
        "python", "javascript", "typescript", "html", "css", "react", "vue", "java", "kotlin", "swift", "rust", "golang", "c++", "c#", "php"
    ))
    return coding and not explicit


def extract_plan(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _safe_target(path: str, workspace: Path) -> Path:
    target = (workspace / path).resolve()
    root = workspace.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Refusing path outside workspace: {path}")
    return target


def _run_with_heartbeat(command: str, workspace: Path, progress: Progress) -> str:
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    started = time.monotonic()
    while process.poll() is None:
        elapsed = int(time.monotonic() - started)
        progress(f"Running command ({elapsed}s): {command}")
        time.sleep(5)
        if elapsed >= 180:
            process.kill()
            break
    stdout, stderr = process.communicate()
    return (
        f"Command: {command}\nExit code: {process.returncode}\n"
        f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    )


def _open_browser(workspace: Path, url: str, progress: Progress) -> str:
    if not url:
        candidate = workspace / "index.html"
        if candidate.exists():
            url = candidate.resolve().as_uri()
        else:
            url = "http://127.0.0.1:8000/"

    if url.startswith("file:") and (workspace / "index.html").exists():
        # Browser security is more reliable through HTTP, especially on Android.
        subprocess.Popen(
            [os.environ.get("PYTHON", "python3"), "-m", "http.server", "8000", "--bind", "127.0.0.1"],
            cwd=workspace,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = "http://127.0.0.1:8000/"
        time.sleep(1)

    progress(f"Opening browser: {url}")
    if shutil.which("termux-open-url"):
        completed = subprocess.run(["termux-open-url", url], text=True, capture_output=True)
        return f"Browser command: termux-open-url {url}\nExit code: {completed.returncode}\n{completed.stderr}"
    if shutil.which("am"):
        completed = subprocess.run(
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            text=True,
            capture_output=True,
        )
        return f"Browser command: am start ... {url}\nExit code: {completed.returncode}\n{completed.stdout}{completed.stderr}"
    opened = webbrowser.open(url)
    return f"Browser open requested for {url}; accepted={opened}."


def execute_action(action: dict[str, Any], workspace: Path, progress: Progress) -> str:
    kind = str(action.get("type") or action.get("action") or "").strip().lower()
    progress(f"Action: {kind or 'unknown'}")
    if kind in {"respond", "message"}:
        return str(action.get("message") or action.get("content") or "")
    if kind == "write_file":
        target = _safe_target(str(action.get("path") or ""), workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(action.get("content") or "")
        target.write_text(content, encoding="utf-8")
        progress(f"Wrote {target} ({len(content)} characters)")
        return f"Wrote {target} ({target.stat().st_size} bytes)."
    if kind == "mkdir":
        target = _safe_target(str(action.get("path") or ""), workspace)
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory {target}."
    if kind in {"run", "shell", "run_command"}:
        command = str(action.get("command") or "").strip()
        if not command:
            return "No command supplied."
        return _run_with_heartbeat(command, workspace, progress)
    if kind in {"open_browser", "browser"}:
        return _open_browser(workspace, str(action.get("url") or "").strip(), progress)
    return f"Unsupported action type: {kind or 'missing'}"


def selected_action(plan: dict[str, Any]) -> dict[str, Any] | None:
    action = plan.get("action")
    if isinstance(action, dict):
        return action
    candidates = plan.get("candidates")
    index = plan.get("selected_index", 0)
    if isinstance(candidates, list) and candidates:
        try:
            item = candidates[int(index)]
        except (ValueError, IndexError, TypeError):
            item = candidates[0]
        if isinstance(item, dict) and isinstance(item.get("action"), dict):
            return item["action"]
    return None


def run_structured_loop(
    *,
    initial_text: str,
    original_request: str,
    ask: Callable[[str], Any],
    workspace: Path | None = None,
    max_steps: int = 8,
    progress: Progress | None = None,
) -> str:
    workspace = (workspace or Path.cwd()).resolve()
    progress = progress or (lambda _message: None)
    current = initial_text
    evidence: list[str] = []
    for step in range(1, max_steps + 1):
        plan = extract_plan(current)
        if not plan:
            return current if not evidence else current + "\n\nExecution evidence:\n" + "\n".join(evidence)
        action = selected_action(plan)
        if not action:
            return "Structured plan did not contain an executable action.\n" + current
        progress(f"Step {step}/{max_steps}: preparing {action.get('type', 'action')}")
        result = execute_action(action, workspace, progress)
        evidence.append(f"Step {step}: {result}")
        kind = str(action.get("type") or "").lower()
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or str(action.get("message") or "")) + "\n\nExecution evidence:\n" + "\n".join(evidence)
        followup = (
            "Continue the same user task. Use the real execution result below. "
            "Return exactly one JSON object with objective, success_criteria, deterministic_checks, candidates, "
            "selected_index, selection_reason, and action. Choose the next smallest executable action. "
            "Do not repeat completed actions. When all criteria are verified, use action type respond. "
            "For browser demos, ensure an open_browser action is eventually used.\n\n"
            f"Original request: {original_request}\n\nExecution result:\n{result}"
        )
        progress(f"Step {step}/{max_steps}: asking model for next action")
        response = ask(followup)
        current = getattr(response, "text", str(response))
    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)
