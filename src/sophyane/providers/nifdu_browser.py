"""NIFDU Chromium/ChatGPT browser intelligence provider.

This provider deliberately reuses the existing external NIFDU/CDP
bridge. Chromium control and screenshot intelligence remain owned by
that bridge rather than being reimplemented inside Sophyane.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
from pathlib import Path
from typing import Any

from sophyane.providers.base import (
    Provider,
    ProviderError,
)


DEFAULT_LOOP = (
    Path.home()
    / ".local"
    / "share"
    / "sophyane-chatgpt-loop"
)


def _selection_path() -> Path:
    value = os.environ.get(
        "SOPHYANE_NIFDU_CALLABLE_FILE"
    )

    if value:
        return Path(
            value
        ).expanduser()

    return (
        Path.home()
        / ".local"
        / "share"
        / "sophyane-chatgpt-loop"
        / "sophyane-nifdu-callable.json"
    )


def _load_module(
    path: Path,
):
    name = (
        "_sophyane_nifdu_bridge_"
        + str(
            abs(
                hash(
                    str(path)
                )
            )
        )
    )

    spec = (
        importlib.util
        .spec_from_file_location(
            name,
            path,
        )
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise ProviderError(
            "Unable to load NIFDU bridge "
            f"module: {path}"
        )

    module = (
        importlib.util
        .module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def _run_result(
    value: Any,
) -> Any:
    if inspect.isawaitable(
        value
    ):
        return asyncio.run(
            value
        )

    return value


def _normalise_response(
    value: Any,
) -> str:
    if value is None:
        raise ProviderError(
            "NIFDU bridge returned no response"
        )

    if isinstance(
        value,
        str,
    ):
        text = value.strip()

        if text:
            return text

    if isinstance(
        value,
        dict,
    ):
        for key in (
            "text",
            "response",
            "answer",
            "output",
            "content",
            "message",
        ):
            candidate = value.get(
                key
            )

            if isinstance(
                candidate,
                str,
            ) and candidate.strip():
                return candidate.strip()

        return json.dumps(
            value,
            ensure_ascii=False,
        )

    text = str(
        value
    ).strip()

    if not text:
        raise ProviderError(
            "NIFDU bridge produced an empty response"
        )

    return text


class NifduBrowserProvider(
    Provider
):
    """ChatGPT intelligence through the existing NIFDU browser loop."""

    provider_id = "nifdu_browser"

    def __init__(
        self,
        *,
        model: str = "chatgpt-browser",
        timeout: int = 180,
        **_: Any,
    ):
        self.model = model
        self.timeout = int(
            timeout
        )

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        selection_file = (
            _selection_path()
        )

        if not selection_file.is_file():
            raise ProviderError(
                "NIFDU callable selection is missing: "
                f"{selection_file}"
            )

        selection = json.loads(
            selection_file.read_text(
                encoding="utf-8",
            )
        )

        module_path = Path(
            selection["module"]
        )

        if not module_path.is_file():
            raise ProviderError(
                "NIFDU bridge module is missing: "
                f"{module_path}"
            )

        module = _load_module(
            module_path
        )

        user_prompt = prompt

        if system_prompt:
            user_prompt = (
                system_prompt.strip()
                + "\n\n"
                + prompt
            )

        args = list(
            selection.get(
                "args",
                [],
            )
        )

        def invoke(
            callable_object,
        ):
            # Existing NIFDU bridge contract:
            #
            #   ask(prompt, image=None)
            #
            # The bridge owns its timeout through
            # SOPHYANE_CHATGPT_TIMEOUT. Never pass provider timeout
            # positionally because it would be interpreted as an
            # image path.
            if not args:
                return callable_object()

            if len(args) == 1:
                return callable_object(
                    user_prompt
                )

            if (
                len(args) == 2
                and args[0] in {
                    "prompt",
                    "message",
                    "request",
                    "query",
                    "text",
                    "instruction",
                    "user_prompt",
                }
                and args[1] in {
                    "image",
                    "screenshot",
                    "image_path",
                    "screenshot_path",
                }
            ):
                return callable_object(
                    user_prompt,
                    None,
                )

            raise ProviderError(
                "Unsupported NIFDU bridge callable "
                f"signature: {args!r}"
            )

        if (
            selection["kind"]
            == "function"
        ):
            target = getattr(
                module,
                selection["name"],
            )

            result = invoke(
                target
            )

        else:
            cls = getattr(
                module,
                selection["class"],
            )

            instance = cls()

            target = getattr(
                instance,
                selection["name"],
            )

            result = invoke(
                target
            )

        return _normalise_response(
            _run_result(
                result
            )
        )
