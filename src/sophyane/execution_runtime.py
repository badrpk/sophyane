"""Observable bounded execution loop for structured software actions."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]
MAX_CAPTURE = 12000


def coding_request_needs_language(message: str) -> bool:
    text = f" {message.lower()} "
    coding = any(word in text for word in (
        "build", "make", "create", "develop", "game", "app", "website", "api", "script", "program"
    ))
    explicit = any(word in text for word in (
        "python", "javascript", " js ", "typescript", " ts ", "html", "css", "react", "vue", "java", "kotlin", "swift", "rust", "golang", "c++", "cpp", "c#", "php", "bash", "shell"
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


def looks_like_truncated_plan(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") and any(
        marker in stripped
        for marker in ('"objective"', '"action"', '"candidates"', '"success_criteria"')
    ) and extract_plan(stripped) is None


def _safe_target(path: str, workspace: Path) -> Path:
    if not path.strip():
        raise ValueError("File action did not contain a path.")
    target = (workspace / path).resolve()
    root = workspace.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Refusing path outside workspace: {path}")
    return target


def _clip(value: str) -> str:
    if len(value) <= MAX_CAPTURE:
        return value
    return value[:MAX_CAPTURE] + f"\n… output truncated ({len(value) - MAX_CAPTURE} more characters)"


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
    next_update = 0
    while process.poll() is None:
        elapsed = int(time.monotonic() - started)
        if elapsed >= next_update:
            progress(f"Running command ({elapsed}s): {command}")
            next_update += 5
        time.sleep(1)
        if elapsed >= 180:
            process.kill()
            break
    stdout, stderr = process.communicate()
    return (
        f"Command: {command}\nExit code: {process.returncode}\n"
        f"STDOUT:\n{_clip(stdout)}\nSTDERR:\n{_clip(stderr)}"
    )


def _open_browser(workspace: Path, url: str, progress: Progress) -> str:
    candidate = workspace / "index.html"
    if not url:
        if not candidate.exists():
            return "Browser launch blocked: index.html does not exist in the current project workspace."
        url = candidate.resolve().as_uri()

    if url.startswith("file:") and candidate.exists():
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
        return f"Browser command: termux-open-url {url}\nExit code: {completed.returncode}\n{completed.stdout}{completed.stderr}"
    if shutil.which("am"):
        completed = subprocess.run(
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            text=True,
            capture_output=True,
        )
        return f"Browser command: am start ... {url}\nExit code: {completed.returncode}\n{completed.stdout}{completed.stderr}"
    opened = webbrowser.open(url)
    return f"Browser open requested for {url}; accepted={opened}."


def execute_action(action: dict[str, Any], workspace: Path, progress: Progress) -> tuple[bool, str]:
    kind = str(action.get("type") or action.get("action") or "").strip().lower()
    progress(f"Action: {kind or 'unknown'}")
    if kind in {"respond", "message"}:
        return True, str(action.get("message") or action.get("content") or "")
    if kind in {"write_file", "append_file"}:
        target = _safe_target(str(action.get("path") or ""), workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(action.get("content") or "")
        mode = "a" if kind == "append_file" else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(content)
        verb = "Appended to" if mode == "a" else "Wrote"
        progress(f"{verb} {target} ({len(content)} characters)")
        return True, f"{verb} {target} ({target.stat().st_size} total bytes)."
    if kind == "mkdir":
        target = _safe_target(str(action.get("path") or ""), workspace)
        target.mkdir(parents=True, exist_ok=True)
        return True, f"Created directory {target}."
    if kind in {"run", "shell", "run_command", "bash"}:
        command = str(action.get("command") or action.get("content") or "").strip()
        if not command:
            return False, "Command action did not contain a command."
        return True, _run_with_heartbeat(command, workspace, progress)
    if kind in {"open_browser", "browser"}:
        result = _open_browser(workspace, str(action.get("url") or "").strip(), progress)
        return (not result.startswith("Browser launch blocked")), result
    return False, f"Unsupported or missing action type: {kind or 'missing'}"


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


def _recovery_prompt(workspace: Path, original_request: str, broken: str) -> str:
    return (
        "Your previous JSON action was truncated or invalid and was NOT executed. "
        "Return exactly one small valid JSON object. Keep content below 2200 characters. "
        "For larger files, use write_file for the first chunk and append_file for later chunks. "
        "Valid actions: write_file, append_file, mkdir, run_command, open_browser, respond. "
        "Do not include markdown fences or commentary.\n\n"
        f"Workspace: {workspace}\nOriginal request: {original_request}\n"
        f"Broken response prefix:\n{broken[:1200]}"
    )


def run_structured_loop(
    *,
    initial_text: str,
    original_request: str,
    ask: Callable[[str], Any],
    workspace: Path | None = None,
    max_steps: int = 12,
    progress: Progress | None = None,
) -> str:
    workspace = (workspace or Path.cwd()).resolve()
    progress = progress or (lambda _message: None)
    current = initial_text
    evidence: list[str] = []
    recovery_attempts = 0
    step = 1
    while step <= max_steps:
        plan = extract_plan(current)
        if not plan:
            if looks_like_truncated_plan(current) and recovery_attempts < 2:
                recovery_attempts += 1
                progress(f"Recovering truncated JSON plan ({recovery_attempts}/2)")
                response = ask(_recovery_prompt(workspace, original_request, current))
                current = getattr(response, "text", str(response))
                continue
            if evidence:
                return "Execution stopped: provider returned non-executable text before verification.\n\n" + "\n".join(evidence)
            return current

        action = selected_action(plan)
        if not action:
            return "Execution stopped safely: structured plan contained no executable action."
        progress(f"Step {step}/{max_steps}: preparing {action.get('type', 'action')}")
        ok, result = execute_action(action, workspace, progress)
        evidence.append(f"Step {step}: {result}")
        if not ok:
            return "Execution stopped safely.\n\n" + "\n".join(evidence)
        kind = str(action.get("type") or action.get("action") or "").lower()
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or str(action.get("message") or "")) + "\n\nExecution evidence:\n" + "\n".join(evidence)

        followup = (
            "Continue the same user task using only the isolated workspace. Use the real execution result below. "
            "Return exactly one SMALL valid JSON object, with content below 2200 characters. "
            "For larger source files, use write_file then append_file chunks. "
            "Valid action types are write_file, append_file, mkdir, run_command, open_browser, and respond. "
            "Do not inspect parent directories or repeat completed actions. Compile/test after writing. "
            "When every requested criterion is verified, use respond. If a browser demo was requested, create "
            "index.html and then use open_browser. Do not merely describe opening it.\n\n"
            f"Workspace: {workspace}\nOriginal request: {original_request}\n\nExecution result:\n{result}"
        )
        progress(f"Step {step}/{max_steps}: asking model for next action")
        response = ask(followup)
        current = getattr(response, "text", str(response))
        step += 1
    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)
