from __future__ import annotations

import inspect

import sophyane.providers.fallback as fallback


def test_cloud_session_overrides_persisted_fallback_order() -> None:
    source = inspect.getsource(
        fallback.build_fallback_provider
    )

    assert (
        "SOPHYANE_STRICT_CLOUD_PROVIDER_CHAIN_V1"
        in source
    )

    assert (
        'session_mode == "cloud_llm"'
        in source
    )

    assert (
        "order = ["
        in source
    )


def test_cloud_session_blocks_bootstrap_local_rescue() -> None:
    source = inspect.getsource(
        fallback.FallbackProvider.generate
    )

    assert (
        "SOPHYANE_STRICT_CLOUD_BOOTSTRAP_BOUNDARY_V2"
        in source
    )

    assert (
        'session_mode == "cloud_llm"'
        in source
    )

    assert (
        "SOPHYANE_DISABLE_LOCAL_FALLBACK"
        in source
    )

    assert (
        "and not strict_cloud"
        in source
    )
