from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sophyane.code_memory.compose as compose


@dataclass
class FakeChunk:
    id: str
    language: str
    text: str
    path: str = "main.cpp"


VALID_CPP = r'''
#include <iostream>
#include <string>

struct JournalEntry {
    std::string kind;
    std::string payload;
};

int main() {
    JournalEntry item{"api_response", "ok"};
    std::cout << item.kind << ":" << item.payload << "\n";
    return 0;
}
'''


def test_cpp_request_classifier():
    assert compose._looks_cpp_request(
        "Write a C++ deterministic replay tool."
    )

    assert compose._looks_cpp_request(
        "Implement this in cpp."
    )

    # Mixed-language requests deliberately retain current Python behavior.
    assert not compose._looks_cpp_request(
        "Provide Python/C++ implementations."
    )

    assert not compose._looks_cpp_request(
        "Write Python code."
    )


def test_valid_cpp_passes_local_syntax_validation():
    assert compose._validate_cpp(
        VALID_CPP
    ) == []


def test_invalid_cpp_fails_local_syntax_validation():
    errors = compose._validate_cpp(
        "int main( { return 0; }"
    )

    assert errors
    assert "syntax validation failed" in errors[0]


def test_cpp_chunk_selection():
    chunk = FakeChunk(
        id="cpp-good",
        language="cpp",
        text=VALID_CPP,
    )

    result, used = compose.compose_cpp_from_chunks(
        [chunk]
    )

    assert result is not None
    assert "#include" in result
    assert used == ["cpp-good"]


def test_python_chunk_is_not_used_for_cpp():
    chunk = FakeChunk(
        id="python",
        language="python",
        text=(
            "def main():\n"
            "    print('wrong language')\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ) * 5,
        path="main.py",
    )

    result, used = compose.compose_cpp_from_chunks(
        [chunk]
    )

    assert result is None
    assert used == []


def test_source_has_no_browser_open_in_cpp_branch():
    source = Path(
        "src/sophyane/code_memory/compose.py"
    ).read_text(
        encoding="utf-8",
    )

    cpp_start = source.index(
        "elif _looks_cpp_request(message):"
    )

    python_start = source.index(
        "\n    else:",
        cpp_start,
    )

    cpp_branch = source[
        cpp_start:python_start
    ]

    assert "open_browser" not in cpp_branch
    assert "index.html" not in cpp_branch
    assert "main.cpp" in cpp_branch
