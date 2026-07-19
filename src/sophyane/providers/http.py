"""Shared standard-library HTTP helpers."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from sophyane.providers.base import ProviderError
from sophyane.version import __version__


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    request_headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Sophyane/{__version__}",
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )

    result_holder: dict[str, str] = {}
    error_holder: dict[str, BaseException] = {}

    def request_worker() -> None:
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                result_holder["body"] = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
        except BaseException as error:  # propagate in the calling thread
            error_holder["error"] = error

    print(
        f"       ◌ Waiting for provider response from {url}",
        flush=True,
    )

    started = time.monotonic()
    worker = threading.Thread(
        target=request_worker,
        name="sophyane-http-request",
        daemon=True,
    )
    worker.start()

    while worker.is_alive():
        worker.join(timeout=5.0)
        if worker.is_alive():
            elapsed = int(time.monotonic() - started)
            print(
                "       ◌ Provider request still running "
                f"({elapsed}s elapsed)",
                flush=True,
            )

    elapsed = int(time.monotonic() - started)

    if "error" in error_holder:
        error = error_holder["error"]

        if isinstance(error, urllib.error.HTTPError):
            error_body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise ProviderError(
                f"HTTP {error.code}: {error_body[:1500]}"
            ) from error

        if isinstance(error, urllib.error.URLError):
            raise ProviderError(
                f"Connection failed: {error.reason}"
            ) from error

        if isinstance(error, TimeoutError):
            raise ProviderError(
                f"Request timed out after {timeout} seconds."
            ) from error

        raise error

    body = result_holder.get("body")
    if body is None:
        raise ProviderError(
            "Provider request finished without returning a response body."
        )

    print(
        f"       ✓ Provider response received after {elapsed}s",
        flush=True,
    )

    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise ProviderError(
            f"Provider returned invalid JSON: {body[:1000]}"
        ) from error

    if not isinstance(result, dict):
        raise ProviderError("Provider returned an unexpected response.")

    return result
