"""Observable Sophyane terminal interface with real action execution."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from sophyane.execution_runtime import (
    coding_request_needs_language,
    extract_plan,
    run_structured_loop,
)
from sophyane.version import __version__


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

    def run(self) -> int:
        print(f"\n◆ Sophyane {__version__}")
        print(f"provider {self.config.get('provider')}  model {self.config.get('model')}")
        print("Actions, commands and 5-second progress are shown live. /quit to exit.\n")
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
                self.emit(
                    "Sophyane",
                    "Which language or framework should I use? For a browser game, choose HTML/CSS/JavaScript for direct browser play, or C++ for WebAssembly/Emscripten.",
                )
                continue

            self.emit("You", message)
            self.progress("Thinking and planning")
            try:
                response = self.ask(message)
                text = getattr(response, "text", str(response))
            except Exception as error:  # noqa: BLE001
                self.emit("system", f"Error: {error}")
                continue

            if text.startswith("INTERNAL_COMMAND:"):
                command = text.split(":", 1)[1]
                body, self.config = self.handle_internal(command, self.config)
                self.emit("system", body)
                continue

            if extract_plan(text):
                self.progress("Structured plan received; executing instead of printing JSON")
                try:
                    text = run_structured_loop(
                        initial_text=text,
                        original_request=message,
                        ask=self.ask,
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

    def ask(message: str) -> Any:
        return agent.ask(message)

    return ObservableTUI(
        config=config,
        ask=ask,
        handle_internal=handle_internal_command,
    ).run()
