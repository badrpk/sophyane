from pathlib import Path


def _source() -> str:
    return Path(
        "src/sophyane/providers/local_gguf.py"
    ).read_text(
        encoding="utf-8",
    )


def _generate_region() -> str:
    source = _source()

    marker = (
        "SOPHYANE_LOCAL_GGUF_SINGLE_REAL_GENERATION_V1"
    )

    start = source.index(
        marker
    )

    end = source.index(
        "    def _generate_via_server(",
        start,
    )

    return source[
        start:end
    ]


def test_provider_does_not_probe_readiness_with_real_three_second_generation():
    source = _source()

    assert (
        "_generate_via_server("
        "prompt, system_prompt, request_timeout=3"
        ")"
        not in source
    )

    assert (
        "SOPHYANE_LOCAL_GGUF_SINGLE_REAL_GENERATION_V1"
        in source
    )

    region = _generate_region()

    assert (
        "wait_until_ready("
        in region
    )


def test_real_generation_receives_remaining_provider_budget():
    region = _generate_region()

    assert (
        "remaining ="
        in region
    )

    compact = "".join(
        region.split()
    )

    assert (
        "request_timeout=max("
        in compact
    )

    assert (
        "int("
        in compact
    )


def test_generate_region_contains_exactly_one_real_server_completion():
    region = _generate_region()

    assert (
        region.count(
            "self._generate_via_server("
        )
        == 1
    )


def test_readiness_is_resolved_before_real_generation():
    region = _generate_region()

    readiness = region.index(
        "wait_until_ready("
    )

    generation = region.index(
        "self._generate_via_server("
    )

    assert readiness < generation
