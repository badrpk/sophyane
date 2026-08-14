from __future__ import annotations

import ast
import inspect
from pathlib import Path

import sophyane.code_memory.internet_acquire as internet


def _source() -> str:
    return Path(
        "src/sophyane/code_memory/internet_acquire.py"
    ).read_text(
        encoding="utf-8",
    )


def test_single_token_and_json_generations_remain():
    text = _source()

    tree = ast.parse(
        text
    )

    for name in (
        "_sli_api_token_v5",
        "_sli_github_json_v5",
    ):
        nodes = [
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name == name
            )
        ]

        assert len(nodes) == 1

    assert (
        "_sli_github_json_before_invalid_token_fallback"
        not in text
    )


def test_json_transport_contains_all_final_policies():
    source = inspect.getsource(
        internet._sli_github_json_v5
    )

    for marker in (
        "_sli_token_marked_invalid_v1",
        "_sli_read_cache_v5",
        "_sli_rate_state_v5",
        "_sli_api_headers_v5",
        "_sli_api_headers_without_auth_v1",
        "_sli_mark_invalid_token_v1",
        "_sli_set_rate_state_v5",
        "401",
        "403",
        "429",
    ):
        assert marker in source


def test_v4_alias_points_directly_to_consolidated_transport():
    assert (
        internet._sli_github_json_v4
        is internet._sli_github_json_v5
    )


def test_headers_resolve_consolidated_token():
    assert (
        internet
        ._sli_api_headers_v5
        .__globals__[
            "_sli_api_token_v5"
        ]
        is internet._sli_api_token_v5
    )


def test_429_rate_limit_persists_state_and_returns_stale_cache(
    tmp_path,
    monkeypatch,
):
    import io
    import json
    import time
    import urllib.error

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(
            tmp_path
            / "state"
        ),
    )

    monkeypatch.delenv(
        "GITHUB_TOKEN",
        raising=False,
    )

    monkeypatch.delenv(
        "GH_TOKEN",
        raising=False,
    )

    url = (
        "https://api.github.com/"
        "search/repositories?"
        "q=429-regression"
    )

    stale_payload = {
        "items": [
            {
                "full_name":
                    "probe/stale",
            }
        ]
    }

    internet._sli_write_cache_v5(
        url,
        stale_payload,
    )

    cache_path = (
        internet._sli_cache_path_v5(
            url
        )
    )

    # Cache freshness is controlled by the timestamp stored
    # inside the JSON record, not filesystem mtime.
    record = json.loads(
        cache_path.read_text(
            encoding="utf-8",
        )
    )

    record[
        "timestamp"
    ] = (
        time.time()
        - 10_000_000
    )

    cache_path.write_text(
        json.dumps(
            record
        ),
        encoding="utf-8",
    )

    # Normal cache lookup must now miss.
    assert (
        internet._sli_read_cache_v5(
            url
        )
        is None
    )

    # But the payload must remain available for the
    # explicit stale fallback after rate limiting.
    assert (
        internet._sli_read_cache_v5(
            url,
            allow_stale=True,
        )
        == stale_payload
    )

    calls = []

    def fake_urlopen(
        request,
        timeout=25,
    ):
        calls.append(
            request.full_url
        )

        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {
                "retry-after":
                    "120",
            },
            io.BytesIO(),
        )

    monkeypatch.setattr(
        internet._sli_urlrequest,
        "urlopen",
        fake_urlopen,
    )

    result = (
        internet._sli_github_json_v5(
            url
        )
    )

    rate = (
        internet._sli_rate_state_v5()
    )

    assert len(
        calls
    ) == 1

    assert result == stale_payload

    assert (
        rate.get(
            "reason"
        )
        == "HTTP 429"
    )

    assert int(
        rate.get(
            "reset",
            0,
        )
        or 0
    ) > int(
        time.time()
    )
