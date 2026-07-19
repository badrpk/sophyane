"""Observable Sophyane terminal interface with explicit execution routing."""
from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sophyane.execution_runtime import extract_plan, run_structured_loop, selected_action
from sophyane.version import __version__


def _simple_chat_reply(message: str) -> str | None:
    text = " ".join(message.strip().lower().split())
    if text in {"hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum"}:
        return "Hello! What would you like me to build, fix, research, or explain?"
    if text in {"thanks", "thank you", "thx"}:
        return "You’re welcome."
    return None


def _execution_requested(message: str) -> bool:
    text = " ".join(message.lower().split())
    advice = (
        "what should", "which project", "project should", "ideas", "recommend",
        "suggest", "explain", "tell me about", "what is", "how does", "can i",
        "temperature", "weather", "meaning of", "assess quality", "show code",
        "show json", "interesting information",
    )
    if any(marker in text for marker in advice):
        return False
    actions = (
        r"\bbuild\b", r"\bmake\b", r"\bcreate\b", r"\bdevelop\b",
        r"\bimplement\b", r"\bwrite\b", r"\bfix\b", r"\bpatch\b",
        r"\bcompile\b", r"\brun\b", r"\btest\b", r"\bdeploy\b",
        r"\bopen\b", r"\bshow\b.*\bdemo\b", r"\bcontinue\b",
        r"\bconvert\b", r"\binstall\b", r"\badd\b.*\bicon\b",
        r"\bexecute\b", r"\bstart\b.*\boption\b",
    )
    return any(re.search(pattern, text) for pattern in actions)


def _references_previous_project(message: str) -> bool:
    text = " ".join(message.lower().split())
    markers = (
        "above", "previous", "same project", "this project", "this in",
        "it in browser", "open output", "open demo", "browser demo", "run it",
        "show it", "continue", "compile it", "test it", "fix it", "of this",
        "create icon", "add icon", "this software", "this app", "option 1",
    )
    return any(marker in text for marker in markers)


def _render_nonexecuting_response(text: str) -> str:
    plan = extract_plan(text)
    if not plan:
        return text.strip()
    action = selected_action(plan)
    if isinstance(action, dict):
        kind = str(action.get("type") or action.get("action") or "").lower()
        if kind in {"respond", "message"}:
            return str(action.get("message") or action.get("content") or "").strip()
    for key in ("answer", "response", "message", "content"):
        value = plan.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    objective = str(plan.get("objective") or "").strip()
    if objective.lower().startswith(("explain ", "interpret ", "explore ", "analyze ", "provide ", "respond ")):
        return "The provider returned an instruction instead of an answer. Use /inspect to view the raw reply."
    return objective or "I could not produce a direct answer. Use /inspect or switch model with /setup."


class ObservableTUI:
    def __init__(self, *, config: dict[str, Any], ask: Any, handle_internal: Any) -> None:
        self.config = config
        self.ask = ask
        self.handle_internal = handle_internal
        self.active_workspace: Path | None = None
        self.active_request = ""
        self.history: list[tuple[str, str]] = []
        self.last_raw = ""
        self.last_prompt = ""
        self.last_elapsed = 0.0
        self.last_mode = "none"
        self.trace = False

    def emit(self, role: str, text: str) -> None:
        print(f"\n{role}\n  " + text.replace("\n", "\n  ") + "\n", flush=True)

    def progress(self, text: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {text}", file=sys.stderr, flush=True)

    def call_provider(self, message: str, *, timeout: int = 60) -> Any:
        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        started = time.monotonic()
        self.last_prompt = message

        def worker() -> None:
            try:
                results.put(("ok", self.ask(message)))
            except Exception as error:  # noqa: BLE001
                results.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        next_update = 5
        while True:
            try:
                status, value = results.get(timeout=1)
                self.last_elapsed = time.monotonic() - started
                if status == "error":
                    raise value
                return value
            except queue.Empty:
                elapsed = int(time.monotonic() - started)
                if elapsed >= next_update:
                    self.progress(f"Waiting for {self.config.get('provider')} response ({elapsed}s)")
                    next_update += 5
                if elapsed >= timeout:
                    raise TimeoutError(f"{self.config.get('provider')} did not respond within {timeout}s.")

    def _workspace_for(self, message: str) -> Path:
        if self.active_workspace and _references_previous_project(message):
            self.progress(f"Reusing workspace: {self.active_workspace}")
            return self.active_workspace
        workspace = Path.home() / ".sophyane" / "workspaces" / f"task-{int(time.time())}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.active_workspace = workspace
        self.progress(f"Workspace: {workspace}")
        return workspace

    def _context_prompt(self, message: str) -> str:
        recent = self.history[-6:]
        if not recent:
            return message
        context = "\n".join(f"{role}: {content}" for role, content in recent)
        return f"Conversation context:\n{context}\n\nCurrent user message: {message}"

    def _inspect(self) -> str:
        plan = extract_plan(self.last_raw)
        lines = [
            f"Mode: {self.last_mode}",
            f"Provider/model: {self.config.get('provider')} / {self.config.get('model')}",
            f"Provider time: {self.last_elapsed:.2f}s",
            f"Active workspace: {self.active_workspace or 'none'}",
            "",
            "Prompt sent to model:",
            self.last_prompt or "(none)",
            "",
            "Raw model response:",
            self.last_raw or "(none)",
        ]
        if plan:
            action = selected_action(plan)
            lines.extend(["", "Parsed JSON plan:", json.dumps(plan, indent=2, ensure_ascii=False)])
            lines.extend(["", "Selected action:", json.dumps(action, indent=2, ensure_ascii=False) if action else "(none)"])
        if self.active_workspace and self.active_workspace.exists():
            files = [p for p in sorted(self.active_workspace.rglob("*")) if p.is_file()]
            lines.extend(["", "Workspace files:"])
            for path in files[:20]:
                lines.append(f"- {path.relative_to(self.active_workspace)} ({path.stat().st_size} bytes)")
            code_files = [p for p in files if p.suffix.lower() in {".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".h", ".rs", ".java"}]
            for path in code_files[:3]:
                try:
                    content = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                lines.extend(["", f"Code: {path.relative_to(self.active_workspace)}", content[:8000]])
        return "\n".join(lines)

    def run(self) -> int:
        print(f"\n◆ Sophyane {__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print("Defaults are automatic. /inspect shows raw plan, selected action, code and timing. /trace toggles raw replies. /quit exits.\n")
        while True:
            try:
                message = input("❯ ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not message:
                continue
            normalized = " ".join(message.lower().split())
            if normalized in {"exit", "quit", "/quit", "/exit", "ecit"}:
                print("Goodbye.")
                return 0
            if normalized == "/inspect":
                self.emit("inspection", self._inspect())
                continue
            if normalized == "/trace":
                self.trace = not self.trace
                self.emit("system", f"Raw response trace {'enabled' if self.trace else 'disabled'}.")
                continue
            if message.startswith("/"):
                command = message[1:].split()[0]
                if command in {"setup", "status", "providers", "doctor"}:
                    text, self.config = self.handle_internal(command, self.config)
                    self.emit("system", text)
                    continue

            self.emit("You", message)
            quick = _simple_chat_reply(message)
            if quick is not None:
                self.history.extend([("user", message), ("assistant", quick)])
                self.emit("Sophyane", quick)
                continue

            executable = _execution_requested(message)
            context_message = self._context_prompt(message)
            if executable:
                self.last_mode = "execution"
                if _references_previous_project(message) and self.active_request:
                    request_for_model = (
                        f"Continue the existing project. New instruction: {context_message}\n\n"
                        f"Original request: {self.active_request}\nExisting workspace: {self.active_workspace}\n"
                        "Return exactly one compact JSON action. Never place more than 1200 characters in file content; use append_file chunks."
                    )
                else:
                    self.active_request = message
                    request_for_model = (
                        f"Execute this request: {context_message}\n\nChoose practical defaults automatically. "
                        "Return exactly one compact JSON action. Never place more than 1200 characters in file content; use append_file chunks."
                    )
            else:
                self.last_mode = "chat"
                request_for_model = (
                    "Answer the current user directly, using the conversation context. Do not return a plan, objective, JSON, "
                    f"tool action, or instruction to another assistant.\n\n{context_message}"
                )

            self.progress("Thinking and planning" if executable else "Getting direct response")
            try:
                response = self.call_provider(request_for_model)
                text = getattr(response, "text", str(response))
                self.last_raw = text
            except Exception as error:  # noqa: BLE001
                self.emit("system", f"Error: {error}")
                continue

            if self.trace:
                self.emit("raw model response", text)

            if executable:
                if extract_plan(text) or text.lstrip().startswith("{"):
                    self.progress("Structured plan received; executing")
                    try:
                        workspace = self._workspace_for(message)
                        text = run_structured_loop(
                            initial_text=text,
                            original_request=request_for_model,
                            ask=lambda prompt: self.call_provider(prompt),
                            workspace=workspace,
                            max_steps=12,
                            progress=self.progress,
                        )
                    except Exception as error:  # noqa: BLE001
                        text = f"Execution loop failed: {error}"
                else:
                    text = "Execution did not start because the provider returned no executable action. Use /inspect to review the raw reply."
            else:
                text = _render_nonexecuting_response(text)

            self.history.extend([("user", message), ("assistant", text)])
            self.history = self.history[-12:]
            self.emit("Sophyane", text)


def run_observable_tui(*, config: dict[str, Any], verbose: bool = False) -> int:
    from sophyane.agent import SophyaneAgent
    from sophyane.logging_config import configure_logging
    from sophyane.main import create_provider, handle_internal_command
    from sophyane.memory import MemoryStore

    logger = configure_logging(verbose)
    agent = SophyaneAgent(create_provider(config), MemoryStore(), logger)
    return ObservableTUI(config=config, ask=agent.ask, handle_internal=handle_internal_command).run()
