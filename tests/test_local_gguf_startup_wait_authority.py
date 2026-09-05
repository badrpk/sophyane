from pathlib import Path


SOURCE = Path(
    "src/sophyane/providers/local_gguf.py"
)


def _source() -> str:
    return SOURCE.read_text(
        encoding="utf-8",
    )


def test_startup_wait_uses_lifecycle_boolean_authority():
    source = _source()

    assert (
        "SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1"
        in source
    )

    assert (
        "server_loading = bool("
        in source
    )

    assert (
        "server_started"
        in source[
            source.index(
                "SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1"
            ):
            source.index(
                "SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1"
            ) + 1000
        ]
    )


def test_long_wait_is_preserved_for_verified_startup():
    source = _source()

    marker = source.index(
        "SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1"
    )

    section = source[
        marker:
        marker + 1800
    ]

    assert "if server_loading:" in section
    assert "70.0" in section
    assert "remaining - 2.0" in section


def test_short_wait_remains_for_unsuccessful_startup():
    source = _source()

    marker = source.index(
        "SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1"
    )

    section = source[
        marker:
        marker + 2200
    ]

    assert "else:" in section
    assert "8.0" in section


def test_human_message_markers_no_longer_control_wait():
    source = _source()

    marker = source.index(
        "SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1"
    )

    section = source[
        marker:
        marker + 900
    ]

    assert '"startup already"' not in section
    assert '"still starting"' not in section
