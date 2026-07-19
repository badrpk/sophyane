"""Bounded execution loop for structured software actions."""
from __future__ import annotations

import json
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Callable


_LANGUAGE_ALIASES = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "py": "Python",
    "python3": "Python",
    "cpp": "C++",
    "cxx": "C++",
    "c++": "C++",
    "csharp": "C#",
    "cs": "C#",
    "golang": "Go",
    "sh": "Bash",
    "shell": "Bash",
    "bash": "Bash",
    "html": "HTML/CSS/JavaScript",
    "web": "HTML/CSS/JavaScript",
    "choose best": "choose best",
    "best": "choose best",
}


def normalize_language(value: str) -> str:
    raw = value.strip()
    return _LANGUAGE_ALIASES.get(raw.lower(), raw)


def _requests_terminal_output(message: str) -> bool:
    text = message.lower()
    return any(token in text for token in ("in bash", "in terminal", "terminal demo", "console demo", "play in bash", "play in terminal"))


def coding_request_needs_language(message: str) -> bool:
    text = message.lower()
    coding = any(word in text for word in ("build", "make", "create", "develop", "game", "app", "website", "api", "script", "program"))
    explicit = any(word in text for word in (
        "python", " py ", "javascript", " js ", "typescript", " ts ", "html", "css", "react", "vue",
        "java", "kotlin", "swift", "rust", "golang", " go ", "c++", "cpp", "c#", "php", "bash", "shell"
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


def execute_action(action: dict[str, Any], workspace: Path) -> str:
    kind = str(action.get("type") or action.get("action") or "").strip().lower()
    if kind in {"respond", "message"}:
        return str(action.get("message") or action.get("content") or "")
    if kind == "write_file":
        target = _safe_target(str(action.get("path") or ""), workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(action.get("content") or ""), encoding="utf-8")
        return f"Wrote {target} ({target.stat().st_size} bytes)."
    if kind == "mkdir":
        target = _safe_target(str(action.get("path") or ""), workspace)
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory {target}."
    if kind in {"run", "shell", "run_command"}:
        command = str(action.get("command") or "").strip()
        if not command:
            return "No command supplied."
        completed = subprocess.run(command, shell=True, cwd=workspace, text=True, capture_output=True, timeout=120)
        return f"Command: {command}\nExit code: {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    if kind in {"open_browser", "browser"}:
        url = str(action.get("url") or "").strip()
        if not url:
            url = (workspace / "index.html").resolve().as_uri()
        opened = webbrowser.open(url)
        return f"Browser open requested for {url}; accepted={opened}."
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


def run_structured_loop(*, initial_text: str, original_request: str, ask: Callable[[str], Any], workspace: Path | None = None, max_steps: int = 8) -> str:
    workspace = (workspace or Path.cwd()).resolve()
    current = initial_text
    evidence: list[str] = []
    for step in range(1, max_steps + 1):
        plan = extract_plan(current)
        if not plan:
            return current if not evidence else current + "\n\nExecution evidence:\n" + "\n".join(evidence)
        action = selected_action(plan)
        if not action:
            return "Structured plan did not contain an executable action.\n" + current
        result = execute_action(action, workspace)
        evidence.append(f"Step {step}: {result}")
        kind = str(action.get("type") or "").lower()
        if kind in {"respond", "message", "open_browser", "browser"}:
            return (result or str(action.get("message") or "")) + "\n\nExecution evidence:\n" + "\n".join(evidence)
        followup = (
            "Continue the same user task recursively using the real execution result. "
            "Return exactly one JSON object with objective, success_criteria, deterministic_checks, candidates, "
            "selected_index, selection_reason, and action. Choose the next smallest executable action. "
            "After building, run deterministic checks; repair failures; when verified, use action type respond. "
            "Do not ask again for a language or framework because it has already been selected.\n\n"
            f"Original request: {original_request}\n\nExecution result:\n{result}"
        )
        response = ask(followup)
        current = getattr(response, "text", str(response))
    return "Stopped after bounded execution loop.\n\n" + "\n".join(evidence)


def install_agent_hooks() -> None:
    """Install once so every CLI surface gets clarification and execution loops."""
    from sophyane.agent import AgentResponse, SophyaneAgent

    if getattr(SophyaneAgent, "_task_runtime_installed", False):
        return
    original_ask = SophyaneAgent.ask

    def wrapped(self: Any, message: str) -> Any:
        pending = getattr(self, "_pending_coding_request", "")
        if pending:
            setattr(self, "_pending_coding_request", "")
            language = normalize_language(message)
            terminal_note = ""
            if _requests_terminal_output(pending):
                terminal_note = (
                    "\nThe user explicitly requested a Bash/terminal demo. Build a terminal-playable program and run it in the terminal. "
                    "Do not create or open a browser demo unless the user later asks for one."
                )
            combined = (
                f"{pending}\n\nSelected implementation language/framework: {language}."
                f"{terminal_note}\nThis selection is final for this task. Do not ask for the language/framework again. "
                "Start with the first executable JSON action now."
            )
            response = original_ask(self, combined)
            response.text = run_structured_loop(
                initial_text=response.text,
                original_request=combined,
                ask=lambda prompt: original_ask(self, prompt),
            )
            return response

        if coding_request_needs_language(message):
            setattr(self, "_pending_coding_request", message)
            destination = "terminal" if _requests_terminal_output(message) else "browser"
            if destination == "terminal":
                hint = "For a terminal game, choose Python, JavaScript/Node.js, C++, Rust, or say ‘choose best’."
            else:
                hint = "For a browser game, choose HTML/CSS/JavaScript for direct browser play, or C++ for WebAssembly/Emscripten."
            return AgentResponse(f"Which language or framework should I use? {hint}")

        response = original_ask(self, message)
        if extract_plan(response.text):
            response.text = run_structured_loop(
                initial_text=response.text,
                original_request=message,
                ask=lambda prompt: original_ask(self, prompt),
            )
        return response

    SophyaneAgent.ask = wrapped
    SophyaneAgent._task_runtime_installed = True
