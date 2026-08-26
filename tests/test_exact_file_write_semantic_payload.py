from pathlib import Path

from sophyane.capability_executors import (
    _exact_file_write,
    _parse_exact_file_write,
)


V3_REQUEST = """Create a file named bench_result.txt in the current working directory.
It must contain exactly one line.
That line must begin BENCH_E= and immediately after the equals sign
contain the uppercase words DEVICE, AGENT, and PASS joined by underscores.
End the file with exactly one newline.
After creating it, briefly confirm completion."""


def test_v3_semantic_payload_is_composed_without_post_action_text():
    assert _parse_exact_file_write(V3_REQUEST) == (
        "bench_result.txt",
        "BENCH_E=DEVICE_AGENT_PASS\n",
    )


def test_v3_semantic_payload_executes_exact_bytes(
    tmp_path: Path,
):
    result = _exact_file_write(
        V3_REQUEST,
        tmp_path,
    )

    assert result is not None
    assert (
        result.capability_id
        == "filesystem.write_exact_verified"
    )

    target = tmp_path / "bench_result.txt"

    assert (
        target.read_bytes()
        == b"BENCH_E=DEVICE_AGENT_PASS\n"
    )

    assert (
        result.data["byte_for_byte_verified"]
        is True
    )
    assert result.data["newline_added"] is True
    assert result.data["provider_bypassed"] is True
    assert (
        result.data["provider_selected_action"]
        is False
    )
    assert (
        result.data["runtime_executed_action"]
        is True
    )


def test_held_out_prefix_and_underscore_composition():
    request = """Create a file named result.txt.
It must contain exactly one line.
The line must begin STATUS= and then contain the uppercase words
ALPHA, BETA, and READY joined by underscores.
End the file with exactly one newline.
After writing the file, confirm completion."""

    assert _parse_exact_file_write(request) == (
        "result.txt",
        "STATUS=ALPHA_BETA_READY\n",
    )


def test_held_out_lowercase_hyphen_composition():
    request = """Create a file named state.txt.
It must contain exactly one line.
That line must begin state: and then contain the lowercase words
FAST, SAFE, and DONE joined by hyphens.
End the file with exactly one newline.
Then confirm completion."""

    assert _parse_exact_file_write(request) == (
        "state.txt",
        "state:fast-safe-done\n",
    )


def test_two_word_list_composition():
    request = """Create a file named pair.txt.
It must contain exactly one line.
That line must begin PAIR= and then contain the uppercase words
LEFT and RIGHT joined by underscores.
End the file with exactly one newline.
After creating it, confirm completion."""

    assert _parse_exact_file_write(request) == (
        "pair.txt",
        "PAIR=LEFT_RIGHT\n",
    )


def test_confirmation_instruction_is_not_payload():
    request = """Create a file named proof.txt.
It must contain exactly one line.
That line must begin PROOF= and then contain the uppercase words
RED, GREEN, and BLUE joined by underscores.
End the file with exactly one newline.
After creating it, briefly confirm completion."""

    parsed = _parse_exact_file_write(request)

    assert parsed is not None

    filename, content = parsed

    assert filename == "proof.txt"
    assert content == "PROOF=RED_GREEN_BLUE\n"
    assert "confirm" not in content.casefold()
    assert "creating" not in content.casefold()


def test_newline_instruction_affects_bytes_only():
    request = """Create a file named newline.txt.
It must contain exactly one line.
That line must begin X= and then contain the uppercase words
ONE and TWO joined by underscores.
End the file with exactly one newline.
After creating it, confirm completion."""

    parsed = _parse_exact_file_write(request)

    assert parsed == (
        "newline.txt",
        "X=ONE_TWO\n",
    )

    assert (
        "one newline"
        not in parsed[1].casefold()
    )


def test_sentence_period_is_not_part_of_filename():
    request = """Create a file named result.txt.
It must contain exactly one line.
That line must begin A= and then contain the uppercase words
ONE and TWO joined by underscores.
End the file with exactly one newline."""

    parsed = _parse_exact_file_write(request)

    assert parsed is not None
    assert parsed[0] == "result.txt"


def test_legacy_literal_exact_write_remains_unchanged():
    request = (
        "Create a file named event18.txt containing exactly: "
        "alpha beta gamma with no newline. "
        "Read it back and verify it byte-for-byte"
    )

    assert _parse_exact_file_write(request) == (
        "event18.txt",
        "alpha beta gamma",
    )


def test_legacy_workspace_literal_shape_remains_supported():
    request = (
        "Using filesystem tools, create harness_verify.txt "
        "in the current workspace containing exactly HARNESS_OK "
        "with no newline. Read the file back, verify it "
        "byte-for-byte, and respond only VERIFIED."
    )

    parsed = _parse_exact_file_write(request)

    assert parsed == (
        "harness_verify.txt",
        "HARNESS_OK",
    )


def test_non_exact_general_write_still_falls_through():
    request = (
        "Create a file named notes.txt "
        "containing some useful notes."
    )

    assert (
        _parse_exact_file_write(request)
        is None
    )


def test_conflicting_newline_requirements_fall_through():
    request = """Create a file named conflict.txt.
It must contain exactly one line.
That line must begin X= and then contain the uppercase words A and B joined by underscores.
End the file with exactly one newline and with no newline."""

    # The compositional front-end refuses the contradiction.
    # It must not manufacture X=A_B bytes.
    parsed = _parse_exact_file_write(request)

    assert parsed != (
        "conflict.txt",
        "X=A_B\n",
    )
