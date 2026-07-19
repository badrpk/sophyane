"""Observable Sophyane terminal interface with explicit execution routing."""
from __future__ import annotations

import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sophyane.execution_runtime import (
    coding_request_needs_language,
    extract_plan,
    run_structured_loop,
    selected_action,
)
from sophyane.version import __version__


def _simple_chat_reply(message: str) -> str | None:
    text = message.strip().lower()
    if text in {"hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum"}:
        return "Hello! What would you like me to build, fix, research, or explain?"
    if text in {"thanks", "thank you", "thx"}:
        return "You’re welcome."
    return None


def _execution_requested(message: str) -> bool:
    """Only explicit imperative work requests may execute local actions."""
    text = " ".join(message.lower().split())
    advice_markers = (
        "what should", "which project", "project should", "ideas", "recommend",
        "suggest", "explain", "tell me about", "what is", "how does", "can i",
    )
    if any(marker in text for marker in advice_markers):
        return False
    action_markers = (
        r"\bbuild\b", r"\bmake\b", r"\bcreate\b", r"\bdevelop\b",
        r"\bimplement\b", r"\bwrite\b", r"\bfix\b", r"\bpatch\b",
        r"\bcompile\b", r"\brun\b", r"\btest\b", r"\bdeploy\b",
        r"\bopen\b", r"\bshow\b.*\bdemo\b", r"\bcontinue\b",
    )
    return any(re.search(pattern, text) for pattern in action_markers)


def _references_previous_project(message: str) -> bool:
    text = " ".join(message.lower().split())
    markers = (
        "above", "previous", "same project", "this project", "it in browser",
        "open output", "open demo", "browser demo", "run it", "show it",
        "continue", "compile it", "test it", "fix it",
    )
    return any(marker in text for marker in markers)


def _render_nonexecuting_response(text: str) -> str:
    plan = extract_plan(text)
    if not plan:
        return text
    action = selected_action(plan)
    if isinstance(action, dict):
        kind = str(action.get("type") or action.get("action") or "").lower()
        if kind in {"respond", "message"}:
            return str(action.get("message") or action.get("content") or "").strip()
    objective = str(plan.get("objective") or "").strip()
    reason = str(plan.get("selection_reason") or "").strip()
    return objective or reason or "I could not produce a normal chat response. Please retry or switch model with /setup."


class ObservableTUI:
    def __init__(self, *, config: dict[str, Any], ask: Any, handle_internal: Any) -> None:
        self.config = config
        self.ask = ask
        self.handle_internal = handle_internal
        self.pending_request = ""
        self.active_workspace: Path | None = None
        self.active_request = ""

    def emit(self, role: str, text: str) -> None:
        print(f"\n{role}\n  " + text.replace("\n", "\n  ") + "\n", flush=True)

    def progress(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] {text}", file=sys.stderr, flush=True)

    def call_provider(self, message: str, *, timeout: int = 60) -> Any:
        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                results.put(("ok", self.ask(message)))
            except Exception as error:  # noqa: BLE001
                results.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        started = time.monotonic()
        next_update = 5
        while True:
            try:
                status, value = results.get(timeout=1)
                if status == "error":
                    raise value
                return value
            except queue.Empty:
                elapsed = int(time.monotonic() - started)
                if elapsed >= next_update:
                    self.progress(f"Waiting for {self.config.get('provider')} response ({elapsed}s)")
                    next_update += 5
                if elapsed >= timeout:
                    raise TimeoutError(
                        f"{self.config.get('provider')} did not respond within {timeout}s. "
                        "Check quota/network, use /setup to switch provider, or configure a local model."
                    )

    def _workspace_for(self, message: str) -> Path:
        if self.active_workspace and _references_previous_project(message):
            self.progress(f"Reusing workspace: {self.active_workspace}")
            return self.active_workspace
        workspace = Path.home() / ".sophyane" / "workspaces" / f"task-{int(time.time())}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.active_workspace = workspace
        self.progress(f"Workspace: {workspace}")
        return workspace

    def run(self) -> int:
        print(f"\n◆ Sophyane {__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print("Chat never runs tools. Explicit build/fix/run tasks show actions and 5-second progress. /quit to exit.\n")
        while True:
            try:
                raw = input("❯ ")
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            message = raw.strip()
            if not message:
                continue
            if message in {"/quit", "/exit"}:
                return 0
            if message.startswith("/"):
                command = message[1:].split()[0]
                if command in {"setup", "status", "providers", "doctor"}:
                    text, self.config = self.handle_internal(command, self.config)
                    self.emit("system", text)
                    continue

            if self.pending_request:
                original = self.pending_request
                self.pending_request = ""
                selected = message.strip()
                message = (
                    f"{original}\n\nSelected implementation language/framework: {selected}. "
                    "This selection is final. Do not ask again. Start with a small executable JSON action."
                )
                self.active_request = message
            elif coding_request_needs_language(message) and _execution_requested(message):
                self.pending_request = message
                terminal = any(token in message.lower() for token in ("bash", "terminal", "console"))
                suggestion = (
                    "For a terminal program, choose Python, JavaScript/Node.js, C++, Rust, or say 'choose best'."
                    if terminal
                    else "Choose Python, JavaScript, C++, Rust, or say 'choose best'. Mention browser if you want a browser demo."
                )
                self.emit("Sophyane", f"Which language or framework should I use? {suggestion}")
                continue

            self.emit("You", message)
            quick = _simple_chat_reply(message)
            if quick is not None:
                self.emit("Sophyane", quick)
                continue

            executable = _execution_requested(message)
            if executable and _references_previous_project(message) and self.active_request:
                request_for_model = (
                    f"Continue the existing project for this new instruction: {message}\n\n"
                    f"Original project request: {self.active_request}\n"
                    f"Existing workspace: {self.active_workspace}\n"
                    "Inspect only this workspace. Return one small valid JSON action and continue until verified."
                )
            else:
                request_for_model = message
                if executable:
                    self.active_request = message

            self.progress("Thinking and planning" if executable else "Getting response")
            try:
                response = self.call_provider(request_for_model)
                text = getattr(response, "text", str(response))
            except Exception as error:  # noqa: BLE001
                self.emit("system", f"Error: {error}")
                continue

            if text.startswith("INTERNAL_COMMAND:"):
                command = text.split(":", 1)[1]
                body, self.config = self.handle_internal(command, self.config)
                self.emit("system", body)
                continue

            if executable:
                plan = extract_plan(text)
                if plan or text.lstrip().startswith("{"):
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
                    text = "Execution did not start because the provider returned no executable action. Retry or switch model with /setup."
            else:
                text = _render_nonexecuting_response(text)
            self.emit("Sophyane", text)


def run_observable_tui(*, config: dict[str, Any], verbose: bool = False) -> int:
    from sophyane.agent import SophyaneAgent
    from sophyane.logging_config import configure_logging
    from sophyane.main import create_provider, handle_internal_command
    from sophyane.memory import MemoryStore

    logger = configure_logging(verbose)
    memory = MemoryStore()
    provider = create_provider(config)
    agent = SophyaneAgent(provider, memory, logger)

    return ObservableTUI(
        config=config,
        ask=agent.ask,
        handle_internal=handle_internal_command,
    ).run()
