from pathlib import Path


def test_bare_enter_does_not_begin_live_steering() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "runtime_provider_context_patch.py"
    ).read_text(encoding="utf-8")

    guard = '''if not steering and char in {"\\\\r", "\\\\n"}:
                                    continue'''

    assert guard in source
    assert source.index(guard) < source.index(
        "if not steering:\n"
        "                                    steering = True"
    )
