from pathlib import Path


def test_bare_enter_does_not_begin_live_steering() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "runtime_provider_context_patch.py"
    ).read_text(encoding="utf-8")

    # Verify the guard semantically without depending on whether the source
    # displays one or two escaped backslashes in a literal substring.
    normalized = source.replace("\\\\r", "\\r").replace(
        "\\\\n",
        "\\n",
    )

    condition = (
        'if not steering and char in {"\\r", "\\n"}:'
    )

    assert condition in normalized

    condition_position = normalized.index(condition)
    following = normalized[
        condition_position:
        condition_position + 180
    ]

    assert "continue" in following
