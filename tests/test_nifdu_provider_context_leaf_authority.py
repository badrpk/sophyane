from __future__ import annotations

import os
from pathlib import Path


SOURCE = Path(
    "src/sophyane/runtime_provider_context_patch.py"
)


def test_nifdu_leaf_provider_generation_authority_is_present():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_NIFDU_LEAF_PROVIDER_CALL_AUTHORITY_V1"
        in source
    )

    assert (
        '_session_mode == "nifdu_llm"'
        in source
    )

    assert (
        '_resolved_provider_id'
        in source
    )

    assert (
        '== "nifdu_browser"'
        in source
    )

    assert (
        "provider.generate("
        in source
    )


def test_non_nifdu_self_ask_path_is_preserved():
    source = SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        "self.ask("
        in source
    )

    assert (
        "else:"
        in source
    )


def test_nifdu_provider_creation_is_dedicated_leaf():
    previous = {
        key: os.environ.get(key)
        for key in (
            "SOPHYANE_SESSION_MODE",
            "SOPHYANE_SESSION_PROVIDER",
        )
    }

    try:
        os.environ[
            "SOPHYANE_SESSION_MODE"
        ] = "nifdu_llm"

        os.environ[
            "SOPHYANE_SESSION_PROVIDER"
        ] = "nifdu_browser"

        from sophyane.main import (
            create_provider,
            load_config,
        )

        provider = create_provider(
            load_config()
        )

        assert (
            getattr(
                provider,
                "provider_id",
                None,
            )
            == "nifdu_browser"
        )

        assert callable(
            getattr(
                provider,
                "generate",
                None,
            )
        )

    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(
                    key,
                    None,
                )
            else:
                os.environ[
                    key
                ] = value
