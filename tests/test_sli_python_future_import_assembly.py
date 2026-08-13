from __future__ import annotations

from sophyane.code_memory.compose import (
    compose_python_from_chunks,
)
from sophyane.code_memory.store import CodeChunk


def chunk(chunk_id, text, path):
    return CodeChunk(
        id=chunk_id,
        text=text,
        language="python",
        path=path,
        source="test",
        weight=1.0,
    )


def test_future_import_from_later_root_is_hoisted_and_root_survives():
    first = chunk(
        "first",
        (
            "def first_component():\n"
            "    return 1\n"
        ),
        "/repo/first.py::first_component",
    )

    later = chunk(
        "later",
        (
            "from __future__ import annotations\n\n"
            "def later_component(value: MissingType):\n"
            "    return value\n"
        ),
        "/repo/later.py",
    )

    first.meta = {
        "placement": "function",
        "provides": ["first"],
        "requires": [],
    }

    later.meta = {
        "placement": "python_module",
        "provides": ["later"],
        "requires": [],
    }

    # Both retrieved components are independently valid.
    compile(first.text, "<first>", "exec")
    compile(later.text, "<later>", "exec")

    source, used = compose_python_from_chunks(
        [first, later],
        root_ids=["first", "later"],
    )

    compile(source, "<assembled>", "exec")

    assert "first" in used

    # Authoritative later root must not disappear merely because its
    # module-level future import cannot remain at its original offset.
    assert "later" in used

    # Future import must be represented in the assembled module preamble.
    lines = source.splitlines()

    future_indexes = [
        index
        for index, line in enumerate(lines)
        if line.strip() == "from __future__ import annotations"
    ]

    assert len(future_indexes) == 1

    future_index = future_indexes[0]

    first_code_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("def first_component")
    )

    assert future_index < first_code_index


def test_duplicate_future_imports_are_deduplicated():
    alpha = chunk(
        "alpha",
        (
            "from __future__ import annotations\n\n"
            "def alpha():\n"
            "    return 1\n"
        ),
        "/repo/alpha.py",
    )

    beta = chunk(
        "beta",
        (
            "from __future__ import annotations\n\n"
            "def beta():\n"
            "    return 2\n"
        ),
        "/repo/beta.py",
    )

    for item in (alpha, beta):
        item.meta = {
            "placement": "python_module",
            "provides": [item.id],
            "requires": [],
        }

    source, used = compose_python_from_chunks(
        [alpha, beta],
        root_ids=["alpha", "beta"],
    )

    compile(source, "<assembled>", "exec")

    assert used == ["alpha", "beta"]

    assert (
        source.count(
            "from __future__ import annotations"
        )
        == 1
    )
