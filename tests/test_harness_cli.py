from __future__ import annotations

import os

from sophyane.harness_cli import MODES, _apply_mode


def _snapshot_env():
    keys = (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        "SOPHYANE_SLI_CONTINUOUS",
        "SOPHYANE_TOPIC_LEARNING",
    )
    return {key: os.environ.get(key) for key in keys}


def _restore_env(snapshot):
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_public_harness_modes_are_exactly_four():
    assert MODES == (
        "deterministic",
        "internet",
        "local-llm",
        "cloud-llm",
    )


def test_deterministic_mode_disables_cloud_rescue():
    before = _snapshot_env()
    try:
        _apply_mode("deterministic")
        assert os.environ["SOPHYANE_SESSION_MODE"] == "race"
        assert os.environ["SOPHYANE_DISABLE_CLOUD_FALLBACK"] == "1"
        assert "SOPHYANE_SLI_ONLY" not in os.environ
        assert "SOPHYANE_LOCAL_ONLY" not in os.environ
    finally:
        _restore_env(before)


def test_internet_mode_maps_to_sli_graph_without_llm():
    before = _snapshot_env()
    try:
        _apply_mode("internet")
        assert os.environ["SOPHYANE_SESSION_MODE"] == "sli_graph"
        assert os.environ["SOPHYANE_SLI_GRAPH"] == "1"
        assert os.environ["SOPHYANE_SLI_ONLY"] == "1"
        assert "SOPHYANE_LOCAL_ONLY" not in os.environ
    finally:
        _restore_env(before)


def test_local_llm_mode_is_strict_local_only():
    before = _snapshot_env()
    try:
        _apply_mode("local-llm")
        assert os.environ["SOPHYANE_SESSION_MODE"] == "local_llm"
        assert os.environ["SOPHYANE_LOCAL_ONLY"] == "1"
        assert os.environ["SOPHYANE_DISABLE_CLOUD_FALLBACK"] == "1"
        assert "SOPHYANE_SLI_ONLY" not in os.environ
    finally:
        _restore_env(before)


def test_cloud_llm_mode_selects_cloud_policy():
    before = _snapshot_env()
    try:
        _apply_mode("cloud-llm")
        assert os.environ["SOPHYANE_SESSION_MODE"] == "cloud_llm"
        assert "SOPHYANE_LOCAL_ONLY" not in os.environ
        assert "SOPHYANE_SLI_ONLY" not in os.environ
    finally:
        _restore_env(before)


def test_mode_switch_clears_stale_mutually_exclusive_flags():
    before = _snapshot_env()
    try:
        os.environ["SOPHYANE_SLI_ONLY"] = "1"
        os.environ["SOPHYANE_SLI_GRAPH"] = "1"
        os.environ["SOPHYANE_LOCAL_ONLY"] = "1"
        os.environ["SOPHYANE_SLI_CONTINUOUS"] = "1"
        os.environ["SOPHYANE_TOPIC_LEARNING"] = "1"

        _apply_mode("cloud-llm")

        assert os.environ["SOPHYANE_SESSION_MODE"] == "cloud_llm"
        assert "SOPHYANE_SLI_ONLY" not in os.environ
        assert "SOPHYANE_SLI_GRAPH" not in os.environ
        assert "SOPHYANE_LOCAL_ONLY" not in os.environ
        assert "SOPHYANE_SLI_CONTINUOUS" not in os.environ
        assert "SOPHYANE_TOPIC_LEARNING" not in os.environ
    finally:
        _restore_env(before)
