"""Grok-style interactive CLI for Sophyane.

Mirrors the Grok Build CLI interaction model:
- banner + session identity
- scrollback of user / assistant / system events
- slash-command palette (/help, /model, /status, /doctor, /new, /quit, …)
- bottom prompt with multiline support
- live status spinner while the agent runs
- automatic local open-model bootstrap when frontier credits fail
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO

from sophyane.config import load_config, save_config
from sophyane.local_runtime import (
    ensure_local_open_model,
    list_local_models,
    ollama_reachable,
    profile_hardware,
    recommend_models,
)
from sophyane.version import __version__


# ANSI helpers (graceful when not a TTY)
def _supports_color(stream: TextIO) -> bool:
    return hasattr(stream, "isatty") and stream.isatty() and os.environ.get("NO_COLOR") is None


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def magenta(self, text: str) -> str:
        return self._wrap("35", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def blue(self, text: str) -> str:
        return self._wrap("34", text)


def looks_like_coding_task(message: str) -> bool:
    """Return True when a prompt requires repository actions, not prose."""
    text = " ".join(message.lower().split())
    explicit = (
        "apply patch",
        "create a file",
        "edit the file",
        "run the tests",
        "run automated tests",
        "compile the program",
        "fix the bug",
        "debug this",
        "refactor",
        "implement",
        "pytest",
        "test suite",
        "repository",
        "codebase",
    )
    if any(marker in text for marker in explicit):
        return True
    action_verbs = ("build", "create", "develop", "modify", "repair", "write")
    software_objects = (
        "api",
        "application",
        "cli",
        "code",
        "program",
        "service",
        "software",
        "website",
    )
    return any(verb in text.split() for verb in action_verbs) and any(
        noun in text.split() for noun in software_objects
    )


SLASH_COMMANDS: dict[str, str] = {
    "/help": "Show slash commands (Grok-compatible palette)",
    "/status": "Show provider, model, fallback chain, and memory",
    "/session-info": "Show session stats and hardware profile",
    "/model": "Show or switch model: /model [name]",
    "/providers": "List discovered LLM provider plugins",
    "/doctor": "Run self-diagnostics",
    "/local": "Force install/start a hardware-fit open model (Ollama)",
    "/memory": "Show persistent memories",
    "/tools": "List local tools",
    "/new": "Clear session scrollback (alias: /clear)",
    "/clear": "Clear session scrollback",
    "/compact": "Compact local conversation history in memory store",
    "/context": "Show approximate context usage for this session",
    "/copy": "Copy last assistant reply to clipboard when possible",
    "/export": "Export session scrollback to a markdown file",
    "/setup": "Re-run provider setup wizard",
    "/yolo": "Toggle always-approve style auto-continue note",
    "/quit": "Exit Sophyane (alias: /exit)",
    "/exit": "Exit Sophyane",
}


@dataclass
class ScrollEntry:
    role: str  # user | assistant | system | tool
    content: str
    ts: float = field(default_factory=time.time)


class Spinner:
    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, style: Style, stream: TextIO = sys.stderr) -> None:
        self.style = style
        self.stream = stream
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._message = "Working"

    def start(self, message: str = "Working") -> None:
        self._message = message
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        idx = 0
        while not self._stop.wait(0.08):
            frame = self.FRAMES[idx % len(self.FRAMES)]
            line = self.style.cyan(f" {frame} {self._message}…")
            print(f"\r{line}", end="", file=self.stream, flush=True)
            idx += 1

    def stop(self, final: str | None = None) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.3)
            self._thread = None
        # clear spinner line
        width = shutil.get_terminal_size((80, 24)).columns
        print("\r" + " " * max(20, width - 1) + "\r", end="", file=self.stream, flush=True)
        if final:
            print(final, file=self.stream, flush=True)


class GrokStyleTUI:
    """Interactive REPL shaped like the Grok Build CLI."""

    def __init__(
        self,
        *,
        config: dict[str, Any],
        ask: Callable[[str], Any],
        handle_internal: Callable[[str, dict[str, Any]], tuple[str, dict[str, Any]]],
        create_provider: Callable[[dict[str, Any]], Any],
        rebuild_agent: Callable[[Any, dict[str, Any]], None],
        show_status: Callable[[dict[str, Any]], str],
        list_providers: Callable[[], str],
        verbose: bool = False,
    ) -> None:
        self.config = config
        self.ask = ask
        self.handle_internal = handle_internal
        self.create_provider = create_provider
        self.rebuild_agent = rebuild_agent
        self.show_status = show_status
        self.list_providers_fn = list_providers
        self.verbose = verbose
        self.style = Style(_supports_color(sys.stdout))
        self.spinner = Spinner(self.style)
        self.scrollback: list[ScrollEntry] = []
        self.session_started = time.time()
        self.turn_count = 0
        self.yolo = False
        self._last_assistant = ""

    # --- rendering -----------------------------------------------------

    def _rule(self, char: str = "─") -> str:
        width = shutil.get_terminal_size((80, 24)).columns
        return self.style.dim(char * max(40, min(width, 100)))

    def banner(self) -> None:
        provider = self.config.get("provider", "?")
        model = self.config.get("model", "?")
        hw = profile_hardware()
        print()
        print(self.style.bold(self.style.cyan(f"  ◆ Sophyane {__version__}")))
        print(self.style.dim("  Terminal agentic harness  ·  Grok-style CLI"))
        print(self._rule())
        print(
            f"  {self.style.green('provider')} {provider}  "
            f"{self.style.green('model')} {model}  "
            f"{self.style.green('hw')} {hw.tier}/{hw.ram_mb}MB"
        )
        print(
            self.style.dim(
                "  Type a message · /help for commands · /local for open models · /quit to exit"
            )
        )
        print(self._rule())
        print()

    def _emit(self, role: str, content: str) -> None:
        self.scrollback.append(ScrollEntry(role=role, content=content))
        s = self.style
        if role == "user":
            label = s.bold(s.blue("You"))
        elif role == "assistant":
            label = s.bold(s.magenta("Sophyane"))
            self._last_assistant = content
        elif role == "system":
            label = s.bold(s.yellow("system"))
        else:
            label = s.bold(s.cyan(role))
        print(f"{label}")
        for line in content.splitlines() or [""]:
            print(f"  {line}")
        print()

    def _prompt_label(self) -> str:
        return self.style.bold(self.style.cyan("❯ "))

    def _read_input(self) -> str | None:
        """Read a prompt. Empty line after text ends multiline; bare empty skips."""
        try:
            first = input(self._prompt_label())
        except EOFError:
            print()
            return None
        except KeyboardInterrupt:
            print()
            print(self.style.dim("  (Ctrl+C) use /quit to exit, or send an empty cancel"))
            return ""

        if not first.endswith("\\"):
            return first

        # Multiline: lines ending with \ continue (Grok-like draft continuation).
        lines = [first[:-1]]
        while True:
            try:
                nxt = input(self.style.dim("… "))
            except (EOFError, KeyboardInterrupt):
                break
            if nxt.endswith("\\"):
                lines.append(nxt[:-1])
            else:
                lines.append(nxt)
                break
        return "\n".join(lines)

    # --- slash commands ------------------------------------------------

    def _help_text(self) -> str:
        lines = ["Slash commands (Grok-compatible):", ""]
        for name, desc in SLASH_COMMANDS.items():
            lines.append(f"  {name:<14} {desc}")
        lines.append("")
        lines.append("Also: @path hints, /remember, /forget, /files, /read, /shell, /daemon-tick")
        return "\n".join(lines)

    def handle_slash(self, raw: str) -> bool:
        """Return True if the command was handled (including quit)."""
        parts = raw.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in {"/quit", "/exit"}:
            self._emit("system", "Goodbye.")
            raise SystemExit(0)

        if cmd in {"/help", "/?"}:
            self._emit("system", self._help_text())
            return True

        if cmd in {"/new", "/clear"}:
            self.scrollback.clear()
            self.turn_count = 0
            self._emit("system", "Session scrollback cleared.")
            return True

        if cmd == "/session-info":
            hw = profile_hardware()
            elapsed = int(time.time() - self.session_started)
            text = "\n".join(
                [
                    f"Sophyane {__version__}",
                    f"Turns: {self.turn_count}",
                    f"Scrollback entries: {len(self.scrollback)}",
                    f"Session age: {elapsed}s",
                    f"Provider: {self.config.get('provider')} / {self.config.get('model')}",
                    f"Hardware: tier={hw.tier} cpus={hw.cpus} ram={hw.ram_mb}MB "
                    f"disk_free={hw.disk_free_mb}MB arch={hw.arch} virt={hw.virtualization}",
                    f"Ollama: {'up' if ollama_reachable() else 'down'}",
                    f"Local models: {', '.join(list_local_models()) or 'none'}",
                    f"YOLO auto-approve note: {'on' if self.yolo else 'off'}",
                ]
            )
            self._emit("system", text)
            return True

        if cmd == "/context":
            chars = sum(len(e.content) for e in self.scrollback)
            text = (
                f"Session context (approx): {chars} chars · "
                f"{len(self.scrollback)} entries · turns={self.turn_count}"
            )
            self._emit("system", text)
            return True

        if cmd == "/compact":
            # Drop older scrollback, keep last 8 entries.
            if len(self.scrollback) > 8:
                self.scrollback = self.scrollback[-8:]
            self._emit("system", "Compacted session scrollback to the latest entries.")
            return True

        if cmd == "/copy":
            if not self._last_assistant:
                self._emit("system", "Nothing to copy yet.")
                return True
            copied = False
            for tool in ("xclip", "wl-copy", "pbcopy"):
                if shutil.which(tool):
                    try:
                        import subprocess

                        subprocess.run(
                            [tool],
                            input=self._last_assistant,
                            text=True,
                            check=False,
                            capture_output=True,
                        )
                        copied = True
                        break
                    except OSError:
                        pass
            if copied:
                self._emit("system", "Last reply copied to clipboard.")
            else:
                self._emit(
                    "system",
                    "Clipboard tool not found. Last reply begins:\n"
                    + self._last_assistant[:400],
                )
            return True

        if cmd == "/export":
            from pathlib import Path

            out = Path.home() / ".sophyane" / "exports"
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"session-{int(time.time())}.md"
            lines = [f"# Sophyane session {__version__}", ""]
            for entry in self.scrollback:
                lines.append(f"## {entry.role}")
                lines.append(entry.content)
                lines.append("")
            path.write_text("\n".join(lines), encoding="utf-8")
            self._emit("system", f"Exported to {path}")
            return True

        if cmd == "/yolo":
            self.yolo = not self.yolo
            self._emit(
                "system",
                "Always-approve mode "
                + ("enabled (be careful)." if self.yolo else "disabled."),
            )
            return True

        if cmd == "/model":
            if not arg:
                rec = recommend_models()
                local = list_local_models()
                lines = [
                    f"Current: {self.config.get('provider')}/{self.config.get('model')}",
                    f"Local Ollama models: {', '.join(local) or 'none'}",
                    "Recommended for this hardware:",
                ]
                for name, size, ram, note in rec:
                    lines.append(f"  - {name} (~{size}MB, min RAM {ram}MB) — {note}")
                lines.append("Switch: /model llama3.2:1b   or   /local")
                self._emit("system", "\n".join(lines))
                return True
            self.config["model"] = arg
            if ollama_reachable() or arg in list_local_models() or ":" in arg:
                self.config["provider"] = "ollama"
            save_config(self.config)
            try:
                provider = self.create_provider(self.config)
                self.rebuild_agent(provider, self.config)
                self._emit("system", f"Model set to {self.config['provider']}/{arg}")
            except Exception as error:  # noqa: BLE001
                self._emit("system", f"Model updated in config but provider rebuild failed: {error}")
            return True

        if cmd == "/local":
            self._bootstrap_local(force=True)
            return True

        if cmd in {"/status", "/providers", "/doctor", "/setup", "/tools", "/memory"}:
            key = cmd[1:]
            if key in {"status", "providers", "doctor", "setup"}:
                text, self.config = self.handle_internal(key, self.config)
                if key == "setup":
                    try:
                        provider = self.create_provider(self.config)
                        self.rebuild_agent(provider, self.config)
                    except Exception as error:  # noqa: BLE001
                        text = f"{text}\nProvider rebuild note: {error}"
                self._emit("system", text)
                return True
            # Route tools/memory through the agent.
            response = self.ask(cmd)
            self._emit("assistant", getattr(response, "text", str(response)))
            return True

        # Unknown slash → let agent handle (/remember, /shell, …)
        return False

    def _bootstrap_local(self, force: bool = False) -> bool:
        self.spinner.start("Installing hardware-fit open model")
        messages: list[str] = []

        def progress(msg: str) -> None:
            messages.append(msg)
            self.spinner._message = msg[:60]

        try:
            result = ensure_local_open_model(progress=progress, force_pull=force)
        finally:
            self.spinner.stop()

        if result.ok:
            self.config = load_config()
            try:
                provider = self.create_provider(self.config)
                self.rebuild_agent(provider, self.config)
            except Exception as error:  # noqa: BLE001
                self._emit(
                    "system",
                    f"{result.message}\nProvider rebuild failed: {error}",
                )
                return False
            detail = result.message
            if messages:
                detail += "\n" + "\n".join(f"  · {m}" for m in messages[-6:])
            self._emit("system", detail)
            return True

        self._emit(
            "system",
            "Local open-model bootstrap failed:\n"
            f"{result.message}\n"
            "Free disk space, install Ollama manually, or top up API credits.",
        )
        return False

    def _maybe_auto_local(self, error_text: str) -> bool:
        from sophyane.local_runtime import is_credit_or_auth_failure

        if not is_credit_or_auth_failure(error_text):
            return False
        self._emit(
            "system",
            "Frontier LLM APIs unavailable (quota/credits/auth). "
            "Auto-installing a hardware-compatible open model…",
        )
        return self._bootstrap_local(force=False)

    # --- main loop -----------------------------------------------------

    def run(self) -> int:
        self.banner()
        while True:
            raw = self._read_input()
            if raw is None:
                return 0
            message = raw.strip()
            if not message:
                continue

            if message.startswith("/"):
                try:
                    handled = self.handle_slash(message)
                except SystemExit:
                    return 0
                if handled:
                    continue

            self.turn_count += 1
            self._emit("user", message)
            self.spinner.start("Thinking")
            try:
                response = self.ask(message)
                text = getattr(response, "text", str(response))
            except Exception as error:  # noqa: BLE001
                self.spinner.stop()
                err = str(error)
                if self._maybe_auto_local(err):
                    self.spinner.start("Retrying with local model")
                    try:
                        response = self.ask(message)
                        text = getattr(response, "text", str(response))
                    except Exception as retry_error:  # noqa: BLE001
                        self.spinner.stop()
                        self._emit("system", f"Retry failed: {retry_error}")
                        continue
                else:
                    self._emit("system", f"Error: {err}")
                    continue
            finally:
                self.spinner.stop()

            # INTERNAL_COMMAND bridge
            if text.startswith("INTERNAL_COMMAND:"):
                command = text.split(":", 1)[1]
                body, self.config = self.handle_internal(command, self.config)
                self._emit("system", body)
                continue

            # Detect soft provider failures returned as text and auto-heal.
            if any(
                token in text.lower()
                for token in (
                    "all llm providers failed",
                    "insufficient_quota",
                    "could not reach any working llm",
                    "provider unavailable",
                    "top up api credits",
                )
            ):
                if self._maybe_auto_local(text):
                    self.spinner.start("Retrying with local model")
                    try:
                        response = self.ask(message)
                        text = getattr(response, "text", str(response))
                    except Exception as retry_error:  # noqa: BLE001
                        self.spinner.stop()
                        self._emit("system", f"Retry failed: {retry_error}")
                        continue
                    finally:
                        self.spinner.stop()

            self._emit("assistant", text)
            if getattr(response, "should_exit", False):
                return 0


def run_grok_style_tui(
    *,
    config: dict[str, Any],
    verbose: bool,
) -> int:
    """Entry used by the public CLI for interactive sessions."""
    from sophyane.agent import SophyaneAgent
    from sophyane.logging_config import configure_logging
    from sophyane.main import (
        create_provider,
        handle_internal_command,
        list_providers,
        show_status,
    )
    from sophyane.memory import MemoryStore

    logger = configure_logging(verbose)
    memory = MemoryStore()

    state: dict[str, Any] = {
        "agent": None,
        "provider": None,
        "config": config,
        "tui": None,
    }

    def rebuild(provider: Any, cfg: dict[str, Any]) -> None:
        state["agent"] = SophyaneAgent(provider, memory, logger)
        state["provider"] = provider
        state["config"] = cfg

    try:
        provider = create_provider(config)
    except Exception as error:  # noqa: BLE001
        print(f"Provider bootstrap: {error}", file=sys.stderr)
        print("Attempting local open-model install…", file=sys.stderr)
        result = ensure_local_open_model(
            progress=lambda m: print(f"  · {m}", file=sys.stderr),
        )
        if not result.ok:
            print(result.message, file=sys.stderr)
            return 1
        config = load_config()
        provider = create_provider(config)

    rebuild(provider, config)

    def ask(message: str) -> Any:
        if not looks_like_coding_task(message):
            return state["agent"].ask(message)

        # Interactive coding requests must use the same inspect/plan/act/verify
        # loop as one-shot CLI requests. Never let the chat model imitate tools.
        from sophyane.agent import AgentResponse
        from sophyane.live_coding_doer import LiveProgressReporter
        from sophyane.strict_interactive_doer import (
            StrictInteractiveCodingDoerRuntime,
        )

        active_tui = state.get("tui")
        if active_tui is not None:
            active_tui.spinner.stop()

        provider = state["provider"]

        def backend(prompt: str, system: str) -> str:
            return provider.generate(prompt, system)

        runtime = StrictInteractiveCodingDoerRuntime(
            backend=backend,
            memory=memory,
            workspace=Path.cwd(),
            max_steps=12,
            protocol_attempts=3,
            progress=LiveProgressReporter(enabled=True),
        )
        result = runtime.run(message)
        summary = (
            "EXECUTION_MODE=repository_coding_agent\n"
            f"GOAL_MET={'true' if result.goal_met else 'false'}\n"
            f"LOOP_STEPS={len(result.steps)}\n"
            f"STOPPED_REASON={result.stopped_reason}\n\n"
            f"{result.final_output}"
        )
        memory.record_message("user", message)
        memory.record_message("assistant", summary)
        return AgentResponse(summary)

    tui = GrokStyleTUI(
        config=state["config"],
        ask=ask,
        handle_internal=handle_internal_command,
        create_provider=create_provider,
        rebuild_agent=rebuild,
        show_status=show_status,
        list_providers=list_providers,
        verbose=verbose,
    )
    state["tui"] = tui
    # Keep config reference live
    def _handle(cmd: str, cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        text, updated = handle_internal_command(cmd, cfg)
        state["config"] = updated
        tui.config = updated
        return text, updated

    tui.handle_internal = _handle
    return tui.run()
