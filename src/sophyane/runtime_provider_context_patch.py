"""Truthful provider dispatch context and heartbeat reporting."""
from __future__ import annotations

import queue
import threading
import time
from typing import Any

from sophyane.runtime_semantic_instruction import (
    apply_live_instruction,
    reset_semantic_request,
)

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
    if _looks_like_provider(value):
        # A concrete provider is authoritative even when it is not a
        # fallback/dispatcher object. Historically this walker only
        # accepted providers exposing ``_providers`` or ``primary``;
        # that discarded dedicated leaf providers such as
        # NifduBrowserProvider and caused the TUI to fall back to stale
        # saved configuration when reporting provider identity.
        if (
            hasattr(value, "_providers")
            or hasattr(value, "primary")
        ):
            return value

        metadata = getattr(
            value,
            "metadata",
            None,
        )

        provider_id = str(
            getattr(
                metadata,
                "provider_id",
                "",
            )
            or getattr(
                value,
                "provider_id",
                "",
            )
            or ""
        ).strip()

        if provider_id:
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
        primary = str(
            getattr(
                provider,
                "primary",
                "",
            )
            or ""
        ).strip().lower()

        if primary:
            return primary

        metadata = getattr(
            provider,
            "metadata",
            None,
        )

        provider_id = str(
            getattr(
                metadata,
                "provider_id",
                "",
            )
            or getattr(
                provider,
                "provider_id",
                "",
            )
            or ""
        ).strip().lower()

        if provider_id:
            return provider_id

    return str(
        getattr(
            tui,
            "config",
            {},
        ).get(
            "provider"
        )
        or "provider"
    ).lower()


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
        metadata = getattr(
            provider,
            "metadata",
            None,
        )

        primary = str(
            getattr(
                provider,
                "primary",
                "",
            )
            or getattr(
                metadata,
                "provider_id",
                "",
            )
            or getattr(
                provider,
                "provider_id",
                "",
            )
            or self.config.get(
                "provider"
            )
            or ""
        ).lower()

        # Normalize the caller-owned timeout without imposing a separate
        # short local-inference deadline at the provider-context layer.
        if primary in {"local_gguf"}:
            # The provider-context wrapper is the live TUI timeout
            # authority. Do not silently reduce the caller/configured provider
            # budget to a short UI deadline. Local GGUF inference and coding
            # requests can legitimately require minutes on CPU/mobile hosts.
            #
            # Explicit call_provider(..., timeout=N) remains authoritative.
            # The normal call path still supplies the TUI/provider timeout
            # chosen by its caller.
            timeout = max(1.0, float(timeout))

        original_message = message
        live_instructions: list[str] = []

        stdin_fd: int | None = None
        saved_terminal: list[Any] | None = None

        # Automated runners may create a pseudo-TTY with `script`.
        # SOPHYANE_NONINTERACTIVE disables live keyboard steering so piped
        # input cannot cancel or restart an active provider generation.
        interactive_input = (
            sys.stdin.isatty()
            and os.environ.get(
                "SOPHYANE_NONINTERACTIVE",
                "",
            ).strip().lower()
            not in {"1", "true", "yes", "on"}
        )

        if interactive_input:
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
                deadline = started + float(timeout)

                def worker() -> None:
                    bind_generation(generation)

                    try:
                        # SOPHYANE_NIFDU_LEAF_PROVIDER_CALL_AUTHORITY_V1
                        #
                        # In NIFDU Browser mode the provider discovered above
                        # is the authoritative ChatGPT/CDP intelligence leaf.
                        #
                        # self.ask may be a higher-level Sophyane dispatcher
                        # that enters the unified execution kernel and task
                        # compiler. Feeding NIFDU action-schema prompts through
                        # that wrapper can transform them into a Sophyane
                        # compiled work packet instead of returning the model's
                        # requested executable action.
                        #
                        # Keep every other provider/session on the historical
                        # self.ask path. Only the dedicated nifdu_llm +
                        # nifdu_browser leaf bypasses that contaminated wrapper.
                        _session_mode = str(
                            os.environ.get(
                                "SOPHYANE_SESSION_MODE",
                                "",
                            )
                            or ""
                        ).strip().lower()

                        _resolved_provider_id = str(
                            getattr(
                                getattr(
                                    provider,
                                    "metadata",
                                    None,
                                ),
                                "provider_id",
                                "",
                            )
                            or getattr(
                                provider,
                                "provider_id",
                                "",
                            )
                            or ""
                        ).strip().lower()

                        _nifdu_leaf_authoritative = (
                            _session_mode == "nifdu_llm"
                            and _resolved_provider_id
                            == "nifdu_browser"
                            and callable(
                                getattr(
                                    provider,
                                    "generate",
                                    None,
                                )
                            )
                        )

                        # SOPHYANE_CODEX_LEAF_PROVIDER_CALL_AUTHORITY_V1
                        #
                        # An explicitly selected Mode-4.3 Codex session is a
                        # dedicated read-only project provider. Routing its
                        # response through self.ask() re-enters Sophyane's task
                        # compiler and can replace the real Codex answer with a
                        # compiled work packet.
                        _codex_leaf_authoritative = (
                            _session_mode == "codex_cli"
                            and _resolved_provider_id
                            == "codex_cli"
                            and callable(
                                getattr(
                                    provider,
                                    "generate",
                                    None,
                                )
                            )
                        )

                        _direct_leaf_authoritative = (
                            _nifdu_leaf_authoritative
                            or _codex_leaf_authoritative
                        )

                        if _direct_leaf_authoritative:
                            value = provider.generate(
                                active_message
                            )
                        else:
                            value = self.ask(
                                active_message
                            )

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

                # Prevent buffered input from the original prompt submission
                # or a multiline paste from being mistaken for live steering.
                steering_ready_at = time.monotonic() + 1.0

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

                                # During the initial grace period, consume and
                                # discard buffered printable input instead of
                                # cancelling the active provider generation.
                                if (
                                    not steering
                                    and now < steering_ready_at
                                ):
                                    continue

                                # A bare Enter can remain in the terminal input
                                # buffer after submitting or approving a request.
                                # It is not a live instruction and must never
                                # cancel a provider generation.
                                if not steering and char in {"\r", "\n"}:
                                    continue

                                # Ignore other non-printable terminal control
                                # bytes unless steering is already active.
                                if (
                                    not steering
                                    and not char.isprintable()
                                ):
                                    continue

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
                            # Clear both the visible live-instruction list and
                            # the semantic state accumulated by
                            # apply_live_instruction(). Otherwise requirements
                            # from before an explicit restart can leak into the
                            # replacement provider prompt.
                            live_instructions.clear()
                            reset_semantic_request(self)
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

                    active = _active_name(self)

                    # Enforce the deadline before inspecting the result queue.
                    # Therefore a reply that becomes visible after the local
                    # 10s boundary can never be accepted/applied.
                    if not steering and time.monotonic() >= deadline:
                        cancel_generation(generation)

                        # Do not wait for the provider worker here. The hard
                        # deadline also bounds how quickly control returns.
                        # The daemon worker may unwind asynchronously, but its
                        # result queue is discarded and can never be applied.

                        # Explicitly discard a result racing with cancellation.
                        try:
                            while True:
                                results.get_nowait()
                        except queue.Empty:
                            pass

                        self.last_elapsed = time.monotonic() - started
                        publish(
                            primary=primary,
                            active=active,
                            mode="timeout",
                        )
                        raise TimeoutError(
                            f"{active} did not respond within "
                            f"{float(timeout):g}s."
                        )

                    if not steering:
                        remaining = max(
                            0.0,
                            deadline - time.monotonic(),
                        )
                        try:
                            status, value = results.get(
                                timeout=min(0.10, remaining)
                            )
                        except queue.Empty:
                            status = ""
                            value = None

                        # Check the deadline again after blocking on the queue.
                        # A result crossing the boundary is late and unusable.
                        completed_at = time.monotonic()
                        if status and completed_at >= deadline:
                            cancel_generation(generation)
                            # Never block past the application deadline.
                            self.last_elapsed = completed_at - started
                            publish(
                                primary=primary,
                                active=active,
                                mode="timeout",
                            )
                            raise TimeoutError(
                                f"{active} response exceeded "
                                f"{float(timeout):g}s and was discarded."
                            )

                        if status:
                            self.last_elapsed = completed_at - started

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
                                    }
                                    and primary in {
                                        "local_gguf",
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
