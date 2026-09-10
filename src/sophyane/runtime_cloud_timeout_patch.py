"""Use a larger provider timeout for cloud models without slowing local models."""
from __future__ import annotations

import os
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
            configured_provider = str(
                getattr(self, "config", {}).get("provider") or ""
            ).strip().lower()
            session_provider = str(
                os.environ.get("SOPHYANE_SESSION_PROVIDER") or ""
            ).strip().lower()
            session_mode = str(
                os.environ.get("SOPHYANE_SESSION_MODE") or ""
            ).strip().lower()

            nifdu_session = (
                configured_provider in {
                    "nifdu_browser",
                    "browser",
                    "chatgpt_browser",
                }
                or session_provider in {
                    "nifdu_browser",
                    "browser",
                    "chatgpt_browser",
                }
                or session_mode == "nifdu_llm"
            )

            local_profile = str(
                os.environ.get("SOPHYANE_LOCAL_PROFILE") or ""
            ).strip().lower()

            if nifdu_session:
                effective = 600
            elif self.small_local and local_profile == "compare":
                # Sequential Mode-3 comparison runs Qwen and Spark one after
                # the other. Preserve the normal 60-second local budget for
                # individual models, but give the two-model benchmark enough
                # wall-clock time to complete on mobile CPU hardware.
                effective = 180
            else:
                effective = 60 if self.small_local else 120

        return current(self, message, timeout=effective)

    setattr(call_provider, "_sophyane_cloud_timeout", True)
    cls.call_provider = call_provider
