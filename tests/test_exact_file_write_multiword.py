from pathlib import Path

from sophyane.capability_executors import (
    _parse_exact_file_write,
    execute_deterministic_capability,
)
from sophyane.unified_execution_kernel import execute_request


REQUEST = (
    "Create a file named event18.txt containing exactly: "
    "Sophyane event 18 learning verification"
)

EXPECTED = b"Sophyane event 18 learning verification"


def test_parse_exact_file_write_accepts_multiword_content():
    assert _parse_exact_file_write(REQUEST) == (
        "event18.txt",
        "Sophyane event 18 learning verification",
    )


def test_deterministic_exact_write_multiword(tmp_path: Path):
    result = execute_deterministic_capability(
        REQUEST,
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "filesystem.write_exact_verified"

    target = tmp_path / "event18.txt"

    assert target.read_bytes() == EXPECTED


def test_unified_kernel_exact_write_multiword(tmp_path: Path):
    result = execute_request(
        REQUEST,
        workspace=tmp_path,
    )

    assert result is not None
    assert result.handled is True
    assert result.ok is True
    assert result.capability == "filesystem.write_exact_verified"

    target = tmp_path / "event18.txt"

    assert target.read_bytes() == EXPECTED


def test_exact_write_does_not_add_newline(tmp_path: Path):
    result = execute_deterministic_capability(
        REQUEST,
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True

    data = (tmp_path / "event18.txt").read_bytes()

    assert data == EXPECTED
    assert not data.endswith(b"\n")
