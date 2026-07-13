"""Shared standard-library HTTP helpers."""

from __future__ import annotations

import json
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

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="replace",
            )
    except urllib.error.HTTPError as error:
        error_body = error.read().decode(
            "utf-8",
            errors="replace",
        )
        raise ProviderError(
            f"HTTP {error.code}: {error_body[:1500]}"
        ) from error
    except urllib.error.URLError as error:
        raise ProviderError(
            f"Connection failed: {error.reason}"
        ) from error
    except TimeoutError as error:
        raise ProviderError(
            f"Request timed out after {timeout} seconds."
        ) from error

    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise ProviderError(
            f"Provider returned invalid JSON: {body[:1000]}"
        ) from error

    if not isinstance(result, dict):
        raise ProviderError("Provider returned an unexpected response.")

    return result
