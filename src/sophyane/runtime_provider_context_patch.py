"""Truthful provider dispatch context and heartbeat reporting."""
from __future__ import annotations

import queue
import threading
import time
from typing import Any

from sophyane.runtime_semantic_instruction import apply_live_instruction

from sophyane.provider_state import publish, snapshot

_PROVIDER_ATTRS = ("provider", "llm", "backend", "dispatcher", "model_provider")
_STATE_ATTRS = ("_quality_active_call_provider", "active_provider", "current_provider", "_quality_active_rescue", "last_provider")


def _looks_like_provider(value: Any) -> bool:
    return value is not None and callable(getattr(value, "generate", None))


def _walk_provider(value: Any, seen: set[int] | None = None, depth: int = 0) -> Any:
    if value is None or depth > 6:
        return None
    seen = seen or set()
    marker = id(value)
    if marker in seen:
        return None
    seen.add(marker)
    if _looks_like_provider(value) and (hasattr(value, "_providers") or hasattr(value, "primary")):
        return value
    owner = getattr(value, "__self__", None)
    found = _walk_provider(owner, seen, depth + 1)
    if found is not None:
        return found
    for attr in _PROVIDER_ATTRS:
        try:
            child = getattr(value, attr, None)
        except Exception:  # noqa: BLE001
            child = None
        found = _walk_provider(child, seen, depth + 1)
        if found is not None:
            return found
    for cell in getattr(value, "__closure__", None) or ():
        try:
            child = cell.cell_contents
        except ValueError:
            continue
        found = _walk_provider(child, seen, depth + 1)
        if found is not None:
            return found
    return None


def _provider_from_tui(tui: Any) -> Any:
    cached = getattr(tui, "_sophyane_provider_dispatcher", None)
    if cached is not None:
        return cached
    provider = _walk_provider(getattr(tui, "ask", None)) or _walk_provider(tui)
    if provider is not None:
        tui._sophyane_provider_dispatcher = provider
    return provider


def _active_name(tui: Any) -> str:
    shared = snapshot()
    if shared.get("active") and shared.get("mode") in {"active", "repair", "rescue", "request"}:
        return str(shared["active"])
    provider = _provider_from_tui(tui)
    if provider is not None:
        for attr in _STATE_ATTRS:
            value = str(getattr(provider, attr, "") or "").strip().lower()
            if value:
                return value
        primary = str(getattr(provider, "primary", "") or "").strip().lower()
        if primary:
            return primary
    return str(getattr(tui, "config", {}).get("provider") or "provider").lower()


def install_provider_context_patch() -> None:
    from sophyane import tui_v2
    if getattr(tui_v2, "_provider_context_patch_installed", False):
        return
    original_init = tui_v2.ObservableTUI.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        provider = _walk_provider(getattr(self, "ask", None))
        if provider is not None:
            self._sophyane_provider_dispatcher = provider

    def call_provider(self: Any, message: str, *, timeout: int = 60) -> Any:
        """Provider call with non-recursive five-second-idle live steering."""
        import os
        import select
        import sys
        import termios
        import tty

        from sophyane.runtime_cancel import (
            bind_generation,
            cancel_generation,
            new_generation,
            release_generation,
        )

        provider = _provider_from_tui(self)
        primary = str(
            getattr(provider, "primary", "")
            or self.config.get("provider")
            or ""
        ).lower()

        if primary in {"local_gguf", "ollama"}:
            timeout = max(timeout, 180)

        original_message = message
        live_instructions: list[str] = []

        stdin_fd: int | None = None
        saved_terminal: list[Any] | None = None

        if sys.stdin.isatty():
            try:
                stdin_fd = sys.stdin.fileno()
                saved_terminal = termios.tcgetattr(stdin_fd)
                tty.setcbreak(stdin_fd)
            except Exception:
                stdin_fd = None
                saved_terminal = None

        try:
            while True:
                if live_instructions:
                    additions = "\n".join(
                        f"- {item}" for item in live_instructions
                    )
                    active_message = apply_live_instruction(
                        self,
                        original_message,
                        live_instructions[-1],
                    )

                    active_message += (
                        "\n\nALL LIVE USER INSTRUCTIONS IN ORDER:\n"
                        + additions
                        + "\n\nUse the current authoritative request and "
                        + "retain every non-conflicting instruction. "
                        + "The latest conflicting instruction has priority. "
                        + "Disregard cancelled unfinished provider output."
                    )
                else:
                    active_message = original_message

                self.last_prompt = active_message
                generation = new_generation()

                publish(
                    primary=primary,
                    active=primary,
                    mode="request",
                )

                results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
                worker_done = threading.Event()
                started = time.monotonic()

                def worker() -> None:
                    bind_generation(generation)
                    try:
                        value = self.ask(active_message)
                        item = ("ok", value)
                    except BaseException as error:  # noqa: BLE001
                        item = ("error", error)
                    finally:
                        worker_done.set()
                        release_generation(generation)

                    try:
                        results.put_nowait(item)
                    except queue.Full:
                        pass

                thread = threading.Thread(
                    target=worker,
                    daemon=True,
                    name="sophyane-provider",
                )
                thread.start()

                next_update = 5
                announced = ""
                steering = False
                typed: list[str] = []
                last_key_time: float | None = None
                instruction_submitted = False
                restart_requested = False

                while True:
                    now = time.monotonic()

                    if stdin_fd is not None:
                        try:
                            readable, _, _ = select.select(
                                [stdin_fd], [], [], 0
                            )
                        except Exception:
                            readable = []

                        if readable:
                            try:
                                raw = os.read(stdin_fd, 1)
                            except OSError:
                                raw = b""

                            if raw:
                                char = raw.decode(
                                    "utf-8",
                                    errors="ignore",
                                )

                                if char == "\x03":
                                    cancel_generation(generation)
                                    raise KeyboardInterrupt

                                if not steering:
                                    steering = True
                                    cancel_generation(generation)
                                    publish(
                                        primary=primary,
                                        active=_active_name(self),
                                        mode="live-steering",
                                    )
                                    self.progress(
                                        "Keyboard input detected; "
                                        "provider output paused"
                                    )
                                    print(
                                        "\n✎ Live instruction: ",
                                        end="",
                                        file=sys.stderr,
                                        flush=True,
                                    )

                                if char in {"\x7f", "\b"}:
                                    if typed:
                                        typed.pop()
                                        print(
                                            "\b \b",
                                            end="",
                                            file=sys.stderr,
                                            flush=True,
                                        )
                                elif char in {"\r", "\n"}:
                                    print(
                                        "",
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                    instruction_submitted = True
                                elif char.isprintable():
                                    typed.append(char)
                                    print(
                                        char,
                                        end="",
                                        file=sys.stderr,
                                        flush=True,
                                    )

                                last_key_time = now

                    if (
                        steering
                        and last_key_time is not None
                        and (
                            instruction_submitted
                            or now - last_key_time >= 12.0
                        )
                    ):
                        instruction = "".join(typed).strip()
                        if instruction:
                            active_message = apply_live_instruction(
                                self,
                                active_message,
                                instruction,
                            )
                        print("", file=sys.stderr, flush=True)

                        normalized = " ".join(
                            instruction.lower().split()
                        )

                        first_word = (
                            normalized.split(maxsplit=1)[0]
                            if normalized
                            else ""
                        )

                        if first_word in {
                            "stop",
                            "/stop",
                            "cancel",
                            "/cancel",
                            "quit",
                            "/quit",
                            "exit",
                            "/exit",
                        }:
                            cancel_generation(generation)
                            worker_done.wait(timeout=2.0)
                            publish(
                                primary=primary,
                                active=_active_name(self),
                                mode="cancelled",
                            )
                            raise RuntimeError(
                                "Operation cancelled by live user instruction."
                            )

                        if first_word in {"pause", "/pause"}:
                            cancel_generation(generation)
                            worker_done.wait(timeout=2.0)
                            publish(
                                primary=primary,
                                active=_active_name(self),
                                mode="paused",
                            )
                            raise RuntimeError(
                                "Operation paused by live user instruction."
                            )

                        restart_phrases = (
                            "restart",
                            "start over",
                            "start from beginning",
                            "start from the beginning",
                            "restart the loop",
                            "go back to first",
                            "go back to start",
                        )

                        matched_restart = next(
                            (
                                phrase
                                for phrase in restart_phrases
                                if (
                                    normalized == phrase
                                    or normalized.startswith(phrase + " ")
                                    or normalized.startswith("/" + phrase + " ")
                                    or normalized == "/" + phrase
                                )
                            ),
                            None,
                        )

                        if matched_restart is not None:
                            live_instructions.clear()
                            cleaned = normalized

                            if cleaned.startswith("/"):
                                cleaned = cleaned[1:]

                            if cleaned.startswith(matched_restart):
                                cleaned = cleaned[len(matched_restart):]

                            cleaned = cleaned.strip(" ,.;:-")

                            if cleaned:
                                live_instructions.append(cleaned)

                            self.progress(
                                "Restarting from the original request"
                            )
                        elif instruction:
                            live_instructions.append(instruction)
                            self.progress(
                                "Live instruction complete; "
                                "restarting provider with all requirements"
                            )
                        else:
                            self.progress(
                                "Empty live instruction ignored"
                            )

                        cancel_generation(generation)
                        worker_done.wait(timeout=2.0)

                        # Discard any late result from the old generation.
                        try:
                            while True:
                                results.get_nowait()
                        except queue.Empty:
                            pass

                        restart_requested = True
                        break

                    if not steering:
                        try:
                            status, value = results.get(timeout=0.10)
                        except queue.Empty:
                            status = ""
                            value = None

                        if status:
                            self.last_elapsed = (
                                time.monotonic() - started
                            )

                            if status == "error":
                                raise value

                            used = _active_name(self)
                            self.progress(
                                f"Provider response received from {used} "
                                f"({self.last_elapsed:.1f}s)"
                            )
                            publish(
                                primary=primary,
                                active=used,
                                mode="idle",
                            )
                            return value

                    elapsed = int(time.monotonic() - started)
                    active = _active_name(self)

                    if not steering:
                        if active != announced:
                            mode = (
                                "cloud rescue"
                                if (
                                    active not in {
                                        "local_gguf",
                                        "ollama",
                                    }
                                    and primary in {
                                        "local_gguf",
                                        "ollama",
                                    }
                                )
                                else "active"
                            )
                            self.progress(
                                f"Provider: {active} ({mode})"
                            )
                            announced = active

                        if elapsed >= next_update:
                            self.progress(
                                f"Waiting for {active} response "
                                f"({elapsed}s). Type to steer; "
                                "Ctrl+C cancels."
                            )
                            next_update += 5

                        if elapsed >= timeout:
                            cancel_generation(generation)
                            worker_done.wait(timeout=2.0)
                            publish(
                                primary=primary,
                                active=active,
                                mode="timeout",
                            )
                            raise TimeoutError(
                                f"{active} did not respond "
                                f"within {timeout}s."
                            )

                    time.sleep(0.02)

                if restart_requested:
                    continue

        except KeyboardInterrupt:
            cancel_generation(generation)
            raise
        finally:
            if stdin_fd is not None and saved_terminal is not None:
                try:
                    termios.tcsetattr(
                        stdin_fd,
                        termios.TCSADRAIN,
                        saved_terminal,
                    )
                except Exception:
                    pass

    tui_v2.ObservableTUI.__init__ = init
    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2._provider_context_patch_installed = True
