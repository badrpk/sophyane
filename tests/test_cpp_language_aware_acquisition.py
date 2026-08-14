from __future__ import annotations

from pathlib import Path

import pytest

import sophyane.code_memory.internet_acquire as internet
from sophyane.code_memory.ingest import (
    _LANG,
    ingest_file,
)
from sophyane.code_memory.store import ChunkStore


CPP_REQUEST = (
    "Implement a deterministic execution journal in C++ "
    "using std::vector, std::thread and std::mutex with "
    "replay of recorded thread scheduling events."
)


def test_cpp_search_queries_preserve_language():
    queries = internet.build_search_queries(
        CPP_REQUEST
    )

    joined = " ".join(
        queries
    ).casefold()

    assert "c++" in joined or "cpp" in joined
    assert "javascript" not in joined
    assert "html5" not in joined
    assert "canvas" not in joined


def test_legacy_cpp_queries_preserve_language():
    queries = internet._queries(
        CPP_REQUEST
    )

    joined = " ".join(
        queries
    ).casefold()

    assert "c++" in joined
    assert "javascript" not in joined
    assert "html5" not in joined
    assert "canvas" not in joined


def test_browser_queries_still_use_browser_terms():
    request = (
        "Build a browser snake game using canvas and JavaScript."
    )

    queries = internet.build_search_queries(
        request
    )

    joined = " ".join(
        queries
    ).casefold()

    assert (
        "javascript" in joined
        or "canvas" in joined
    )


@pytest.mark.parametrize(
    ("suffix", "expected"),
    (
        (".cpp", "cpp"),
        (".cc", "cpp"),
        (".cxx", "cpp"),
        (".hpp", "cpp"),
        (".hh", "cpp"),
        (".hxx", "cpp"),
        (".h", "cpp"),
        (".rs", "rust"),
    ),
)
def test_direct_ingest_language_map(
    suffix: str,
    expected: str,
) -> None:
    assert _LANG[suffix] == expected


def test_direct_cpp_ingest_keeps_cpp_language(
    tmp_path: Path,
) -> None:
    source = tmp_path / "journal.cpp"

    source.write_text(
        """
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>

int main() {
    std::mutex mutex;
    std::vector<int> events{1, 2, 3};
    std::cout << events.size() << "\\n";
    return 0;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    store = ChunkStore()

    before = set(
        store.ids
    )

    assert ingest_file(
        source,
        store=store,
        source="cpp-language-regression",
    ) == 1

    added = [
        store.chunks[chunk_id]
        for chunk_id in store.ids
        if (
            chunk_id not in before
            and chunk_id in store.chunks
        )
    ]

    assert added
    assert added[-1].language == "cpp"
    assert added[-1].path.endswith(
        "journal.cpp"
    )
