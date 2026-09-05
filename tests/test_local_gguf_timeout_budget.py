from pathlib import Path


def test_local_gguf_generation_has_no_hidden_85_90_second_cap() -> None:
    source = Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text(
        encoding="utf-8",
    )

    compact = "".join(
        source.split()
    )

    assert (
        "SOPHYANE_LOCAL_GGUF_GENERATION_BUDGET_V2"
        in source
    )

    assert (
        "SOPHYANE_LOCAL_GGUF_HTTP_TIMEOUT_V2"
        in source
    )

    assert (
        "min(float(self.timeout),90.0)"
        not in compact
    )

    assert (
        "min(self.timeout,85)"
        not in compact
    )

    assert (
        "float(self.timeout)"
        in compact
    )

    assert (
        "elseself.timeout"
        in compact
    )



def test_local_gguf_configured_timeout_is_long_enough_for_coding() -> None:
    from sophyane.config import load_config
    from sophyane.main import create_provider

    config = load_config()

    configured_timeout = int(
        config.get(
            "timeout",
            180,
        )
    )

    provider = create_provider(
        config
    )

    print(
        "configured timeout:",
        configured_timeout,
    )

    print(
        "outer provider:",
        type(provider).__name__,
    )

    print(
        "outer timeout:",
        getattr(
            provider,
            "timeout",
            None,
        ),
    )

    assert configured_timeout >= 300

    assert (
        int(
            getattr(
                provider,
                "timeout",
                0,
            )
        )
        == configured_timeout
    )

    local = None

    for provider_id, candidate in getattr(
        provider,
        "_providers",
        (),
    ):
        print(
            "chain provider:",
            provider_id,
            type(candidate).__name__,
            "timeout=",
            getattr(
                candidate,
                "timeout",
                None,
            ),
        )

        if provider_id == "local_gguf":
            local = candidate
            break

    assert local is not None, (
        "local_gguf is absent from the configured "
        "fallback provider chain"
    )

    assert (
        int(
            getattr(
                local,
                "timeout",
                0,
            )
        )
        == configured_timeout
    )


def test_local_gguf_server_output_budget_exceeds_legacy_768_cap() -> None:
    source = Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_LOCAL_GGUF_OUTPUT_BUDGET_V3"
        in source
    )

    assert (
        "min(self.max_tokens, 768)"
        not in source
    )

    assert (
        "1536"
        in source
    )
