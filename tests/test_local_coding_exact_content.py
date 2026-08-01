from pathlib import Path

from sophyane.unified_execution_kernel import execute_request


def test_python_request_preserves_single_quoted_print_value(
    tmp_path: Path,
) -> None:
    result = execute_request(
        """Create hello.py containing exactly:

print('HELLO_FROM_SOPHYANE')

Run hello.py.
""",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.handled is True
    assert result.ok is True
    assert result.evidence["workspace"] == str(tmp_path.resolve())

    target = tmp_path / "hello.py"

    assert target.exists()
    assert target.read_text(encoding="utf-8") == (
        "def main() -> None:\n"
        "    print('HELLO_FROM_SOPHYANE')\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )

    evidence = result.evidence["evidence"]

    assert evidence[-1]["exit_code"] == 0
    assert evidence[-1]["stdout"] == "HELLO_FROM_SOPHYANE\n"


def test_python_request_preserves_double_quoted_print_value(
    tmp_path: Path,
) -> None:
    result = execute_request(
        'Create greeting.py containing exactly print("DOUBLE_QUOTE_OK").',
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True

    target = tmp_path / "greeting.py"

    assert target.exists()
    assert "print('DOUBLE_QUOTE_OK')" in target.read_text(
        encoding="utf-8"
    )
