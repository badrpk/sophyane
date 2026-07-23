"""Install responsive cancellation for provider calls in the observable TUI."""
from __future__ import annotations

import queue
import threading
import time
from typing import Any


def install_interrupt_patch() -> None:
    from sophyane import tui_v2
    from sophyane.runtime_cancel import cancel_all, reset_cancel

    if getattr(tui_v2.ObservableTUI, "_interrupt_patch_installed", False):
        return

    # Provider-context patch includes responsive cancellation plus live
    # keyboard steering. Do not replace it with the older Ctrl+C-only loop.
    if getattr(tui_v2, "_provider_context_patch_installed", False):
        tui_v2.ObservableTUI._interrupt_patch_installed = True
        return

    def call_provider(self: Any, message: str, *, timeout: int = 60) -> Any:
        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        started = time.monotonic()
        self.last_prompt = message
        reset_cancel()

        def worker() -> None:
            try:
                value = self.ask(message)
                try:
                    results.put_nowait(("ok", value))
                except queue.Full:
                    pass
            except BaseException as error:  # noqa: BLE001
                try:
                    results.put_nowait(("error", error))
                except queue.Full:
                    pass

        threading.Thread(target=worker, daemon=True, name="sophyane-provider").start()
        next_update = 5
        try:
            while True:
                try:
                    status, value = results.get(timeout=0.25)
                    self.last_elapsed = time.monotonic() - started
                    if status == "error":
                        raise value
                    return value
                except queue.Empty:
                    elapsed = int(time.monotonic() - started)
                    if elapsed >= next_update:
                        self.progress(f"Waiting for {self.config.get('provider')} response ({elapsed}s). Ctrl+C cancels.")
                        next_update += 5
                    if elapsed >= timeout:
                        cancel_all()
                        raise TimeoutError(f"{self.config.get('provider')} did not respond within {timeout}s.")
        except KeyboardInterrupt:
            cancel_all()
            self.last_elapsed = time.monotonic() - started
            raise

    tui_v2.ObservableTUI.call_provider = call_provider
    tui_v2.ObservableTUI._interrupt_patch_installed = True
