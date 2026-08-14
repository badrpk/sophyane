from pathlib import Path


def test_local_server_defaults_to_one_parallel_slot() -> None:
    source = Path(
        "src/sophyane/local_server.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_LLAMA_MOBILE_SINGLE_SLOT_V1"
        in source
    )

    assert (
        '"SOPHYANE_LLAMA_PARALLEL"'
        in source
    )

    assert (
        '"--parallel"'
        in source
    )

    assert (
        '"1"'
        in source
    )
