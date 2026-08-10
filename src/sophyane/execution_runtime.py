"""Observable bounded execution loop for structured software actions."""
from __future__ import annotations

# --- sophyane native fast-path hook ---
try:
    from sophyane.native.fast_path import try_fast_path as _sophyane_try_fast_path
except Exception:
    _sophyane_try_fast_path = None
# --- end fast-path import ---


import functools
import hashlib
import http.server
import json
import os
import re
import signal
import shutil
import subprocess
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]
MAX_CAPTURE = 12000
VALID_ACTIONS = {
    "write_file", "append_file", "mkdir", "run", "shell", "run_command", "bash",
    "open_browser", "browser", "respond", "message", "answer", "final_answer", "reply", "run_interactive", "interactive",
    "play_demo", "analyze_log", "verify", "check",
}
_BROWSER_SERVERS: dict[Path, tuple[http.server.ThreadingHTTPServer, threading.Thread, str]] = {}



def _recover_quasi_json_file_action(
    text: str,
) -> dict[str, Any] | None:
    """Recover only an unambiguous triple-quoted file action.

    SOPHYANE_QUASI_JSON_FILE_ACTION_RECOVERY_V3

    Some local coding models emit a JSON-shaped write_file or append_file
    envelope but place source content inside Python triple quotes. That is
    invalid JSON even though the action boundary is explicit.

    Recovery is deliberately narrow:
    - write_file or append_file only
    - explicit path
    - triple-double-quoted or triple-single-quoted content
    - complete outer object
    """
    if not isinstance(text, str):
        return None

    value = text.strip()

    if not value:
        return None

    pattern = (
        r'\s*\{\s*'
        r'["\']action["\']\s*:\s*["\']'
        r'(?P<action>write_file|append_file)'
        r'["\']\s*,\s*'
        r'["\']path["\']\s*:\s*["\']'
        r'(?P<path>[^"\'\r\n]+)'
        r'["\']\s*,\s*'
        r'["\']content["\']\s*:\s*'
        r'(?P<quote>"""|\'\'\')'
        r'(?P<content>.*?)'
        r'(?P=quote)'
        r'\s*\}\s*'
    )

    match = re.fullmatch(
        pattern,
        value,
        flags=re.S,
    )

    if not match:
        return None

    file_path = match.group(
        "path"
    ).strip()

    if not file_path:
        return None

    return {
        "action": match.group(
            "action"
        ),
        "path": file_path,
        "content": match.group(
            "content"
        ),
    }


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
            recovered = _recover_quasi_json_file_action(
                text
            )

            if recovered is not None:
                return recovered

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


def _run_with_heartbeat(
    command: str,
    workspace: Path,
    progress: Progress,
    *,
    timeout: int = 60,
) -> str:
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    started = time.monotonic()
    next_update = 0
    while process.poll() is None:
        elapsed = int(time.monotonic() - started)
        if elapsed >= next_update:
            progress(f"Running command ({elapsed}s): {command}")
            next_update += 5
        time.sleep(1)
        if elapsed >= timeout:
            progress(
                f"Command timed out after {timeout}s: {command}"
            )
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
    stdout, stderr = process.communicate()
    return (
        f"Command: {command}\nExit code: {process.returncode}\n"
        f"STDOUT:\n{_clip(stdout)}\nSTDERR:\n{_clip(stderr)}"
    )


def _run_interactive(command: str, workspace: Path, progress: Progress) -> str:
    progress(f"Interactive terminal demo: {command}")
    print("\n--- Interactive demo started; use its controls and quit key to return to Sophyane ---\n", flush=True)
    completed = subprocess.run(command, shell=True, cwd=workspace)
    print("\n--- Interactive demo ended; returning to Sophyane ---\n", flush=True)
    return f"Interactive command: {command}\nExit code: {completed.returncode}"


def _workspace_server(workspace: Path) -> str:
    root = workspace.resolve()
    existing = _BROWSER_SERVERS.get(root)
    if existing is not None:
        server, thread, base_url = existing
        if thread.is_alive():
            return base_url
        try:
            server.server_close()
        except OSError:
            pass
        _BROWSER_SERVERS.pop(root, None)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True, name=f"sophyane-browser-{server.server_port}")
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    _BROWSER_SERVERS[root] = (server, thread, base_url)
    return base_url


def _verify_served_file(candidate: Path, url: str) -> tuple[bool, str]:
    expected = candidate.read_bytes()
    expected_hash = hashlib.sha256(expected).hexdigest()
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status = getattr(response, "status", 200)
            body = response.read()
    except Exception as error:  # noqa: BLE001
        return False, f"HTTP verification failed: {type(error).__name__}: {error}"
    actual_hash = hashlib.sha256(body).hexdigest()
    if status != 200:
        return False, f"HTTP verification returned status {status}"
    if actual_hash != expected_hash:
        return False, "served browser content does not match the current workspace index.html"
    return True, f"served {len(body)} bytes; SHA-256 matched {expected_hash[:12]}"


def _open_browser(workspace: Path, url: str, progress: Progress) -> str:
    candidate = workspace / "index.html"
    project_launch = not url or url.startswith("file:") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost")

    if project_launch:
        if not candidate.is_file():
            return "Browser launch blocked: index.html does not exist in the current project workspace."
        if candidate.stat().st_size < 100:
            return "Browser launch blocked: index.html is empty or too small to be a usable project."
        base_url = _workspace_server(workspace)
        url = f"{base_url}/index.html?v={candidate.stat().st_mtime_ns}"
        ok, verification = _verify_served_file(candidate, url)
        if not ok:
            return f"Browser launch blocked: {verification}."
        progress(f"Verified browser artifact over HTTP: {verification}")
    else:
        return "Browser launch blocked: external URLs do not verify the current project workspace."

    progress(f"Opening browser: {url}")
    if shutil.which("termux-open-url"):
        completed = subprocess.run(["termux-open-url", url], text=True, capture_output=True)
        return (
            f"Browser file: {candidate}\nBrowser URL: {url}\nHTTP verification: {verification}\n"
            f"Browser command: termux-open-url {url}\nExit code: {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    if shutil.which("am"):
        completed = subprocess.run(
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            text=True,
            capture_output=True,
        )
        return (
            f"Browser file: {candidate}\nBrowser URL: {url}\nHTTP verification: {verification}\n"
            f"Browser command: am start ... {url}\nExit code: {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    opened = webbrowser.open(url)
    return (
        f"Browser file: {candidate}\nBrowser URL: {url}\nHTTP verification: {verification}\n"
        f"Browser open requested; accepted={opened}."
    )


def _normalize_action(value: Any) -> dict[str, Any] | None:
    """Accept common Gemini variants and return one canonical action dict."""
    if not isinstance(value, dict):
        return None

    # SOPHYANE_RUNTIME_FILE_SHAPED_CREATE_ALIAS_V1
    #
    # Keep the runtime independently defensive: a file-shaped provider
    # "create" action is a write_file operation. A bare create action remains
    # unsupported because its intended resource type is ambiguous.
    action_alias = str(
        value.get("action")
        or ""
    ).strip().casefold()

    file_path = str(
        value.get("path")
        or value.get("file")
        or ""
    ).strip()

    has_file_content = (
        "content" in value
        or "text" in value
    )

    if (
        action_alias == "create"
        and file_path
        and has_file_content
    ):
        normalized = dict(value)
        normalized.pop(
            "action",
            None,
        )
        normalized["type"] = "write_file"
        return normalized

    kind = str(value.get("type") or value.get("kind") or value.get("name") or "").strip().lower()
    if kind in {"answer", "final_answer", "reply"}:
        kind = "respond"
    if kind in VALID_ACTIONS:
        normalized = dict(value)
        normalized["type"] = kind
        return normalized

    action_value = value.get("action")
    if isinstance(action_value, str):
        action_kind = action_value.strip().lower()
        if action_kind in {"answer", "final_answer", "reply"}:
            action_kind = "respond"
        if action_kind in VALID_ACTIONS:
            normalized = dict(value)
            normalized["type"] = action_kind
            normalized.pop("action", None)
            return normalized
    if isinstance(action_value, dict):
        nested = _normalize_action(action_value)
        if nested:
            return nested

    for key in VALID_ACTIONS:
        payload = value.get(key)
        if isinstance(payload, dict):
            normalized = dict(payload)
            normalized["type"] = key
            return normalized
        if isinstance(payload, str):
            if key in {"run", "shell", "run_command", "bash", "run_interactive", "interactive", "play_demo"}:
                return {"type": key, "command": payload}
            if key in {"respond", "message"}:
                return {"type": key, "message": payload}

    for key in ("tool", "tool_call", "next_action", "selected_action", "operation", "step"):
        nested = _normalize_action(value.get(key))
        if nested:
            return nested
    return None


def execute_action(action: dict[str, Any], workspace: Path, progress: Progress) -> tuple[bool, str]:
    action = _normalize_action(action) or action
    kind = str(action.get("type") or "").strip().lower()
    progress(f"Action: {kind or 'unknown'}")
    if kind in {"respond", "message"}:
        return True, str(
            action.get("message")
            or action.get("content")
            or action.get("answer")
            or action.get("text")
            or action.get("response")
            or action.get("result")
            or ""
        )
    if kind in {"write_file", "append_file"}:
        target = _safe_target(str(action.get("path") or action.get("file") or ""), workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(action.get("content") or action.get("text") or "")
        mode = "a" if kind == "append_file" else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(content)
        verb = "Appended to" if mode == "a" else "Wrote"
        progress(f"{verb} {target} ({len(content)} characters)")
        return True, f"{verb} {target} ({target.stat().st_size} total bytes)."
    if kind == "mkdir":
        target = _safe_target(str(action.get("path") or action.get("directory") or ""), workspace)
        target.mkdir(parents=True, exist_ok=True)
        return True, f"Created directory {target}."
    if kind in {"run", "shell", "run_command", "bash"}:
        command = str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()
        if not command:
            return False, "Command action did not contain a command."
        try:
            requested_timeout = int(
                action.get("timeout") or 60
            )
        except (TypeError, ValueError):
            requested_timeout = 60

        timeout = max(
            1,
            min(requested_timeout, 1800),
        )

        result = _run_with_heartbeat(
            command,
            workspace,
            progress,
            timeout=timeout,
        )

        exit_code = None

        for line in result.splitlines():
            if not line.startswith("Exit code:"):
                continue

            try:
                exit_code = int(
                    line.split(":", 1)[1].strip()
                )
            except (TypeError, ValueError):
                exit_code = None

            break

        # A command action is successful only when the real process exits 0.
        # Previously every completed command returned ok=True, causing failed
        # installs and failed tests to open the success menu.
        return exit_code == 0, result
    if kind in {"run_interactive", "interactive", "play_demo"}:
        command = str(action.get("command") or action.get("content") or action.get("cmd") or "").strip()
        if not command:
            return False, "Interactive action did not contain a command."
        return True, _run_interactive(command, workspace, progress)
    if kind in {"analyze_log", "verify", "check"}:
        return True, str(action.get("message") or action.get("content") or "Analysis checkpoint accepted; continue with the next concrete action.")
    if kind in {"open_browser", "browser"}:
        result = _open_browser(workspace, str(action.get("url") or "").strip(), progress)
        return (not result.startswith("Browser launch blocked")), result
    return False, f"Unsupported or missing action type: {kind or 'missing'}"


def selected_action(plan: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("action", "next_action", "selected_action", "tool_call", "operation"):
        normalized = _normalize_action(plan.get(key))
        if normalized:
            return normalized

    candidates = plan.get("candidates")
    index = plan.get("selected_index", 0)
    if isinstance(candidates, list) and candidates:
        try:
            item = candidates[int(index)]
        except (ValueError, IndexError, TypeError):
            item = candidates[0]
        normalized = _normalize_action(item)
        if normalized:
            return normalized

    return _normalize_action(plan)


def _recovery_prompt(workspace: Path, original_request: str, broken: str) -> str:
    return (
        "Your previous JSON action was missing, nested incorrectly, truncated, or invalid and was NOT executed. "
        "Return exactly one small valid JSON object whose top-level action is an object with a required type field. "
        "Example: {\"action\":{\"type\":\"write_file\",\"path\":\"main.cpp\",\"content\":\"...\"}}. "
        "Keep content below 2200 characters. For larger files, use write_file then append_file. "
        "Valid types: write_file, append_file, mkdir, run_command, run_interactive, open_browser, respond. "
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
            if looks_like_truncated_plan(current) and recovery_attempts < 3:
                recovery_attempts += 1
                progress(f"Recovering truncated JSON plan ({recovery_attempts}/3)")
                response = ask(_recovery_prompt(workspace, original_request, current))
                current = getattr(response, "text", str(response))
                continue
            if evidence:
                return "Execution stopped: provider returned non-executable text before verification.\n\n" + "\n".join(evidence)
            return current

        action = selected_action(plan)
        if not action:
            if recovery_attempts < 3:
                recovery_attempts += 1
                progress(f"Recovering missing/alternate action schema ({recovery_attempts}/3)")
                response = ask(_recovery_prompt(workspace, original_request, current))
                current = getattr(response, "text", str(response))
                continue
            return "Execution stopped safely: provider repeatedly returned no executable action."

        progress(f"Step {step}/{max_steps}: preparing {action.get('type', 'action')}")
        ok, result = execute_action(action, workspace, progress)
        evidence.append(f"Step {step}: {result}")
        if not ok:
            if recovery_attempts < 3:
                recovery_attempts += 1
                progress(f"Recovering invalid action ({recovery_attempts}/3)")
                response = ask(_recovery_prompt(workspace, original_request, json.dumps(plan)[:1200]))
                current = getattr(response, "text", str(response))
                continue
            return "Execution stopped safely.\n\n" + "\n".join(evidence)

        kind = str(action.get("type") or "").lower()
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or str(action.get("message") or "")) + "\n\nExecution evidence:\n" + "\n".join(evidence)

        followup = (
            "Continue the same user task using only the isolated workspace and the real result below. "
            "Return exactly one SMALL valid JSON object with top-level action.type. Keep content below 2200 characters. "
            "For larger files, use write_file then append_file chunks. Valid types: write_file, append_file, mkdir, "
            "run_command, run_interactive, open_browser, respond. Do not inspect parent directories or repeat completed actions. "
            "Compile/test after writing. For terminal games, use run_interactive for the final playable launch. "
            "When every requested criterion is verified, use respond.\n\n"
            f"Workspace: {workspace}\nOriginal request: {original_request}\n\nExecution result:\n{result}"
        )
        progress(f"Step {step}/{max_steps}: asking model for next action")
        response = ask(followup)
        current = getattr(response, "text", str(response))
        step += 1
    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)
