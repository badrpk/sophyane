from __future__ import annotations

import os
from pathlib import Path

import sophyane.code_memory.internet_acquire as internet


def test_github_state_root_follows_sophyane_home(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(
            tmp_path
            / "state"
        ),
    )

    expected = (
        tmp_path
        / "state"
        / "code_memory"
    )

    assert (
        internet._sli_code_memory_state_root_v1()
        == expected
    )

    assert (
        internet._sli_invalid_token_file_v1()
        == expected
        / "github_invalid_token.json"
    )

    assert (
        internet._sli_rate_state_file_v1()
        == expected
        / "github_rate_state.json"
    )

    assert (
        internet._sli_search_cache_dir_v1()
        == expected
        / "github_search_cache"
    )


def test_invalid_token_state_is_isolated(
    tmp_path,
    monkeypatch,
):
    first = (
        tmp_path
        / "first"
    )

    second = (
        tmp_path
        / "second"
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(first),
    )

    assert (
        internet._sli_token_marked_invalid_v1()
        is False
    )

    internet._sli_mark_invalid_token_v1(
        "probe"
    )

    assert (
        internet._sli_token_marked_invalid_v1()
        is True
    )

    assert (
        internet._sli_invalid_token_file_v1()
        .is_file()
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(second),
    )

    assert (
        internet._sli_token_marked_invalid_v1()
        is False
    )

    assert not (
        internet._sli_invalid_token_file_v1()
        .exists()
    )


def test_invalid_token_suppresses_only_current_state(
    tmp_path,
    monkeypatch,
):
    first = tmp_path / "first"
    second = tmp_path / "second"

    monkeypatch.setenv(
        "GITHUB_TOKEN",
        "probe-token",
    )

    monkeypatch.delenv(
        "GH_TOKEN",
        raising=False,
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(first),
    )

    assert (
        internet._sli_api_token_v5()
        == "probe-token"
    )

    internet._sli_mark_invalid_token_v1(
        "401"
    )

    assert (
        internet._sli_api_token_v5()
        == ""
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(second),
    )

    assert (
        internet._sli_api_token_v5()
        == "probe-token"
    )


def test_search_cache_is_isolated(
    tmp_path,
    monkeypatch,
):
    url = (
        "https://api.github.com/"
        "search/repositories?"
        "q=state-isolation"
    )

    first = tmp_path / "first"
    second = tmp_path / "second"

    payload = {
        "items": [
            {
                "full_name":
                    "probe/first",
            }
        ]
    }

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(first),
    )

    internet._sli_write_cache_v5(
        url,
        payload,
    )

    assert (
        internet._sli_read_cache_v5(
            url
        )
        == payload
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(second),
    )

    assert (
        internet._sli_read_cache_v5(
            url
        )
        is None
    )
