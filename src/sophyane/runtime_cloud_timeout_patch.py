"""Use a larger provider timeout for cloud models without slowing local models."""
from __future__ import annotations

from typing import Any


def install_cloud_timeout_patch(tui_v2: Any) -> None:
    """Make omitted/default TUI timeouts provider-aware.

    Cloud generation can legitimately exceed one minute for planning or complete
    browser artifacts. Explicit timeout values remain authoritative.
    """
    cls = tui_v2.ObservableTUI
    current = cls.call_provider
    if getattr(current, "_sophyane_cloud_timeout", False):
        return

    def call_provider(self: Any, message: str, *, timeout: int | None = None) -> Any:
        effective = timeout
        if effective is None:
            effective = 60 if self.small_local else 120
        return current(self, message, timeout=effective)

    setattr(call_provider, "_sophyane_cloud_timeout", True)
    cls.call_provider = call_provider
