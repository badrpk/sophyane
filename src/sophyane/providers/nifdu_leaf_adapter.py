"""Mode-4 adapter for NIFDU's multi-browser CDP bridge.

Sophyane retains ``nifdu_browser`` as its intelligence authority.
The selected NIFDU browser leaf is supplied through
``SOPHYANE_NIFDU_SITE``.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

from sophyane.providers.base import ProviderError


_ALLOWED_SITES = {
    "chatgpt",
    "claude",
    "gemini",
    "grok",
    "perplexity",
    "poe",
    "copilot",
    "mistral",
    "qwen",
    "kimi",
}


def _bridge_path() -> Path:
    return (
        Path.home()
        / "nifdu"
        / "tools"
        / "nifdu_browser_bridge.py"
    )


def _load_external_bridge() -> ModuleType:
    path = _bridge_path()

    if not path.is_file():
        raise ProviderError(
            "NIFDU multi-browser bridge is missing: "
            f"{path}"
        )

    spec = importlib.util.spec_from_file_location(
        "_sophyane_nifdu_multi_browser_bridge",
        path,
    )

    if spec is None or spec.loader is None:
        raise ProviderError(
            "Unable to load NIFDU multi-browser bridge: "
            f"{path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask(
    prompt: str,
    image=None,
):
    if image:
        raise ProviderError(
            "Selected NIFDU multi-browser leaf does not "
            "declare image transport support."
        )

    site = str(
        os.environ.get(
            "SOPHYANE_NIFDU_SITE",
            "",
        )
    ).strip().lower()

    if site not in _ALLOWED_SITES:
        raise ProviderError(
            "Unsupported NIFDU browser site: "
            f"{site!r}"
        )

    # Mode-4 NIFDU leafs use the same tracked Chromium/CDP
    # lifecycle as the packaged NIFDU browser provider.
    # A live endpoint is reused; otherwise the browser is started
    # before the external multi-browser bridge is invoked.
    from sophyane.browser import launcher

    browser_state = launcher.launch_nifdu_browser()

    if not browser_state.get("ok"):
        detail = str(
            browser_state.get("error")
            or "tracked Chromium/CDP browser failed to start"
        )
        raise ProviderError(
            "NIFDU browser bootstrap failed: "
            + detail
        )

    bridge = _load_external_bridge()

    target = getattr(
        bridge,
        "ask",
        None,
    )

    if not callable(target):
        raise ProviderError(
            "NIFDU multi-browser bridge has no callable ask()"
        )

    human_interaction = getattr(
        bridge,
        "HumanInteractionRequired",
        None,
    )

    try:
        return target(
            prompt,
            site,
        )
    except Exception as error:
        if (
            human_interaction is None
            or not isinstance(
                error,
                human_interaction,
            )
        ):
            raise

        target_id = str(
            getattr(
                error,
                "target_id",
                "",
            )
            or ""
        )

        reason = str(
            getattr(
                error,
                "reason",
                "",
            )
            or ""
        )

        if not target_id:
            raise ProviderError(
                "NIFDU browser requires manual "
                "interaction, but the bound browser "
                "target is unavailable."
            ) from error

        presented = launcher.present_nifdu_browser(
            target_id
        )

        if not presented.get("ok"):
            detail = str(
                presented.get("error")
                or presented.get("reason")
                or "browser presentation failed"
            )

            raise ProviderError(
                "NIFDU browser requires manual "
                "interaction, but the visible browser "
                "could not be presented: "
                + detail
            ) from error

        if reason == "chatgpt_signed_out":
            raise ProviderError(
                "Manual ChatGPT sign-in required. "
                "The existing NIFDU browser target "
                "has been presented; sign in there, "
                "then retry the request."
            ) from error

        if reason == "browser_verification_challenge":
            raise ProviderError(
                "Manual browser verification required. "
                "The existing NIFDU browser target "
                "has been presented; complete the "
                "verification there, then retry the "
                "request."
            ) from error

        raise ProviderError(
            "Manual browser interaction required. "
            "The existing NIFDU browser target has "
            "been presented; complete the required "
            "interaction there, then retry the request."
        ) from error
