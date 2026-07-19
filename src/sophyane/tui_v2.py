"""Observable Sophyane terminal interface with persistent project sessions."""
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


def _clean_message(message: str) -> str:
    """Remove copied terminal prompt glyphs and harmless leading whitespace."""
    value = message.strip()
    while value.startswith(("❯", ">")):
        value = value[1:].lstrip()
    return value


def _simple_chat_reply(message: str) -> str | None:
    text = " ".join(message.strip().lower().split())
    if text in {"hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum"}:
        return "Hello! What would you like me to build, fix, research, or explain?"
    if text in {"thanks", "thank you", "thx"}:
        return "You’re welcome."
    if text in {"sophyane --version", "sophyane -v", "--version", "version"}:
        return f"Sophyane {__version__}"
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
    # Imperative build/edit verbs are execution even when preceded by a benchmark number.
    if re.match(
        r"^\s*(?:\d+[.)]\s+)?(?:build|make|create|design|develop|implement|write|fix|repair|patch|compile|run|test|deploy|open|continue|resume|convert|install|integrate|optimi[sz]e|audit|profile|monitor|simulate|demonstrate|execute|add|remove|change|update|improve|style|reopen|replace|modify)\b",
        text,
    ):
        return True
    actions = (
        r"\bbuild\b", r"\bmake\b", r"\bcreate\b", r"\bdesign\b", r"\bdevelop\b",
        r"\bimplement\b", r"\bwrite\b", r"\bfix\b", r"\brepair\b", r"\bpatch\b",
        r"\bcompile\b", r"\brun\b", r"\btest\b", r"\bre-test\b", r"\bdeploy\b",
        r"\bopen\b", r"\bshow\b.*\bdemo\b", r"\bcontinue\b", r"\bresume\b",
        r"\bconvert\b", r"\binstall\b", r"\bintegrate\b", r"\boptimi[sz]e\b",
        r"\baudit\b", r"\bprofile\b", r"\bmonitor\b", r"\bsimulate\b",
        r"\bdemonstrate\b", r"\bexecute\b", r"\bstart building\b",
        r"\badd\b", r"\bremove\b", r"\bchange\b", r"\bupdate\b", r"\bimprove\b",
        r"\bstyle\b", r"\breopen\b", r"\breplace\b", r"\bmodify\b",
    )
    return any(re.search(pattern, text) for pattern in actions)


def _explicit_new_benchmark(message: str) -> bool:
    """Numbered benchmark prompts are independent unless they say same project."""
    text = message.lower()
    return bool(re.match(r"^\s*\d+[.)]\s+", message)) and not any(
        marker in text for marker in ("same project", "continue", "existing project", "reuse")
    )


def _project_continuation(message: str, has_project: bool) -> bool:
    if not has_project or _explicit_new_benchmark(message):
        return False
    text = " ".join(message.lower().split())
    continuation_verbs = (
        "add ", "remove ", "change ", "update ", "improve ", "make the design",
        "style ", "reopen", "test it", "run it", "open it", "fix it", "modify ",
    )
    if text.startswith(continuation_verbs):
        return True
    markers = (
        "above", "previous", "same project", "this project", "this in", "it in browser",
        "open output", "open demo", "browser demo", "show it", "continue", "resume",
        "compile it", "giving error", "has error", "of this", "create icon", "add icon",
        "this software", "this app", "must survive", "full integration", "working prototype",
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
    return str(plan.get("objective") or "I could not produce a direct answer.").strip()


class ObservableTUI:
    def __init__(self, *, config: dict[str, Any], ask: Any, handle_internal: Any) -> None:
        self.config = config
        self.ask = ask
        self.handle_internal = handle_internal
        self.active_workspace: Path | None = None
        self.active_request = ""
        self.project_requirements: list[str] = []
        self.history: list[tuple[str, str]] = []
        self.last_raw = ""
        self.last_prompt = ""
        self.last_elapsed = 0.0
        self.last_mode = "none"
        self.trace = False

    @property
    def small_local(self) -> bool:
        return str(self.config.get("provider") or "").lower() in {"local_gguf", "ollama"}

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

    def _new_workspace(self) -> Path:
        workspace = Path.home() / ".sophyane" / "workspaces" / f"task-{int(time.time())}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.active_workspace = workspace
        self.progress(f"Workspace: {workspace}")
        return workspace

    def _workspace_for(self, continuing: bool) -> Path:
        if continuing and self.active_workspace:
            self.progress(f"Reusing workspace: {self.active_workspace}")
            return self.active_workspace
        return self._new_workspace()

    def _context_prompt(self, message: str, *, continuing: bool) -> str:
        if self.small_local:
            if continuing and self.active_request:
                return f"Project: {self.active_request[:180]}\nChange: {message[:320]}"
            return message[:600]
        recent = self.history[-2:]
        if not recent:
            return message
        context = "\n".join(f"{role}: {content[:700]}" for role, content in recent)
        return f"Conversation context:\n{context}\n\nCurrent user message: {message}"

    def _inspect(self) -> str:
        plan = extract_plan(self.last_raw)
        lines = [
            f"Mode: {self.last_mode}",
            f"Provider/model: {self.config.get('provider')} / {self.config.get('model')}",
            f"Provider time: {self.last_elapsed:.2f}s",
            f"Active workspace: {self.active_workspace or 'none'}",
            f"Project requirements: {len(self.project_requirements)}",
            "", "Prompt sent to model:", self.last_prompt or "(none)",
            "", "Raw model response:", self.last_raw or "(none)",
        ]
        if plan:
            lines.extend(["", "Parsed JSON plan:", json.dumps(plan, indent=2, ensure_ascii=False)])
        if self.active_workspace and self.active_workspace.exists():
            files = [p for p in sorted(self.active_workspace.rglob("*")) if p.is_file()]
            lines.extend(["", "Workspace files:"])
            for path in files[:30]:
                lines.append(f"- {path.relative_to(self.active_workspace)} ({path.stat().st_size} bytes)")
        return "\n".join(lines)

    def run(self) -> int:
        print(f"\n◆ Sophyane {__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print("Projects keep one workspace across follow-up edits. /new starts a fresh project. /inspect shows raw plan and files. /quit exits.\n")
        while True:
            try:
                message = _clean_message(input("❯ "))
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not message:
                continue
            normalized = " ".join(message.lower().split())
            if normalized in {"exit", "quit", "/quit", "/exit", "ecit"}:
                print("Goodbye.")
                return 0
            if normalized == "/new":
                self.active_workspace = None
                self.active_request = ""
                self.project_requirements.clear()
                self.history.clear()
                self.emit("system", "Project session cleared. The next build request will use a new workspace.")
                continue
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
                self.emit("Sophyane", quick)
                continue

            has_project = bool(self.active_request and self.active_workspace)
            continuing = _project_continuation(message, has_project)
            executable = _execution_requested(message) or continuing
            if _explicit_new_benchmark(message):
                continuing = False
            context_message = self._context_prompt(message, continuing=continuing)

            if executable:
                self.last_mode = "execution"
                if continuing:
                    self.project_requirements.append(message)
                    request_for_model = (
                        f"Continue existing project. {context_message}\n"
                        "Return one compact JSON action using relative paths. Modify existing files; do not start over."
                    )
                else:
                    self.active_request = message
                    self.project_requirements = [message]
                    request_for_model = (
                        f"Execute: {context_message}\n"
                        "Return one compact JSON action or artifact. Use relative paths and verify real output."
                    )
            else:
                self.last_mode = "chat"
                request_for_model = f"Answer directly. No JSON or tool action.\n{context_message}"

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
                self.progress("Execution request received; entering adaptive runtime")
                try:
                    workspace = self._workspace_for(continuing)
                    text = run_structured_loop(
                        initial_text=text,
                        original_request=message,
                        ask=lambda prompt: self.call_provider(prompt),
                        workspace=workspace,
                        max_steps=8 if self.small_local else 16,
                        progress=self.progress,
                    )
                except Exception as error:  # noqa: BLE001
                    text = f"Execution loop failed safely: {error}"
            else:
                text = _render_nonexecuting_response(text)

            self.history.extend([("user", message[:300]), ("assistant", text[:500])])
            self.history = self.history[-4:]
            self.emit("Sophyane", text)


def run_observable_tui(*, config: dict[str, Any], verbose: bool = False) -> int:
    from sophyane.agent import SophyaneAgent
    from sophyane.logging_config import configure_logging
    from sophyane.main import create_provider, handle_internal_command
    from sophyane.memory import MemoryStore

    logger = configure_logging(verbose)
    agent = SophyaneAgent(create_provider(config), MemoryStore(), logger)
    return ObservableTUI(config=config, ask=agent.ask, handle_internal=handle_internal_command).run()
