"""Observable Sophyane terminal interface with real action execution."""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sophyane.execution_runtime import (
    coding_request_needs_language,
    extract_plan,
    run_structured_loop,
)
from sophyane.version import __version__


def _simple_chat_reply(message: str) -> str | None:
    text = message.strip().lower()
    if text in {"hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum"}:
        return "Hello! What would you like me to build, fix, research, or explain?"
    if text in {"thanks", "thank you", "thx"}:
        return "You’re welcome."
    return None


class ObservableTUI:
    def __init__(self, *, config: dict[str, Any], ask: Any, handle_internal: Any) -> None:
        self.config = config
        self.ask = ask
        self.handle_internal = handle_internal
        self.pending_request = ""

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

    def run(self) -> int:
        print(f"\n◆ Sophyane {__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print("Chat replies stay lightweight. Coding tasks show actions, commands and 5-second progress. /quit to exit.\n")
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
                message = f"{original}\n\nUser selected implementation language/framework: {message}"
            elif coding_request_needs_language(message):
                self.pending_request = message
                terminal = any(token in message.lower() for token in ("bash", "terminal", "console"))
                suggestion = (
                    "For a terminal program, choose Python, JavaScript/Node.js, C++, Rust, or say 'choose best'."
                    if terminal
                    else "For a browser project, choose HTML/CSS/JavaScript for direct play, or C++ for WebAssembly/Emscripten."
                )
                self.emit("Sophyane", f"Which language or framework should I use? {suggestion}")
                continue

            self.emit("You", message)
            quick = _simple_chat_reply(message)
            if quick is not None:
                self.emit("Sophyane", quick)
                continue

            is_coding = any(
                token in message.lower()
                for token in ("build", "make", "create", "develop", "game", "app", "website", "api", "script", "program", "fix", "code")
            )
            self.progress("Thinking and planning" if is_coding else "Getting response")
            try:
                response = self.call_provider(message)
                text = getattr(response, "text", str(response))
            except Exception as error:  # noqa: BLE001
                self.emit("system", f"Error: {error}")
                continue

            if text.startswith("INTERNAL_COMMAND:"):
                command = text.split(":", 1)[1]
                body, self.config = self.handle_internal(command, self.config)
                self.emit("system", body)
                continue

            if is_coding and extract_plan(text):
                self.progress("Structured plan received; executing instead of printing JSON")
                try:
                    text = run_structured_loop(
                        initial_text=text,
                        original_request=message,
                        ask=lambda prompt: self.call_provider(prompt),
                        workspace=Path.cwd(),
                        max_steps=8,
                        progress=self.progress,
                    )
                except Exception as error:  # noqa: BLE001
                    text = f"Execution loop failed: {error}"
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
