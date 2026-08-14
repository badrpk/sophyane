from __future__ import annotations

import json
from pathlib import Path

from sophyane.code_memory.acquire import (
    acquire_tree,
)
from sophyane.code_memory.store import (
    ChunkStore,
)


def _write_cpp_tree(
    root: Path,
) -> None:
    (root / "include").mkdir(
        parents=True,
        exist_ok=True,
    )

    (root / "src").mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        root
        / "include"
        / "model.hpp"
    ).write_text(
        (
            "#pragma once\n"
            "\n"
            "struct Model {\n"
            "    int value = 42;\n"
            "};\n"
        ),
        encoding="utf-8",
    )

    (
        root
        / "src"
        / "main.cpp"
    ).write_text(
        (
            '#include "model.hpp"\n'
            "#include <iostream>\n"
            "\n"
            "int main() {\n"
            "    Model model;\n"
            "    std::cout << model.value << \"\\n\";\n"
            "    return 0;\n"
            "}\n"
        ),
        encoding="utf-8",
    )


def test_acquire_tree_has_one_durable_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = (
        tmp_path
        / "state"
    )

    tree = (
        tmp_path
        / "tree"
    )

    tree.mkdir(
        parents=True,
    )

    _write_cpp_tree(
        tree
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(state),
    )

    report = acquire_tree(
        tree,
        source="consolidation-test",
        progress=lambda _message: None,
    )

    durable = ChunkStore()

    assert report[
        "files_scanned"
    ] == 2

    assert report[
        "chunks_added"
    ] == 2

    assert report[
        "memory_size"
    ] == len(
        durable.ids
    )

    assert len(
        durable.ids
    ) == 2

    assert {
        durable.chunks[
            chunk_id
        ].language
        for chunk_id in durable.ids
    } == {
        "cpp",
    }


def test_duplicate_reacquire_adds_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = (
        tmp_path
        / "state"
    )

    tree = (
        tmp_path
        / "tree"
    )

    tree.mkdir(
        parents=True,
    )

    _write_cpp_tree(
        tree
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(state),
    )

    first = acquire_tree(
        tree,
        source="first-pass",
        progress=lambda _message: None,
    )

    second = acquire_tree(
        tree,
        source="second-pass",
        progress=lambda _message: None,
    )

    assert first[
        "chunks_added"
    ] == 2

    assert second[
        "chunks_added"
    ] == 0

    assert second[
        "skipped_dupes"
    ] == 2

    assert second[
        "memory_size"
    ] == first[
        "memory_size"
    ]


def test_acquisition_event_records_durable_size(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = (
        tmp_path
        / "state"
    )

    tree = (
        tmp_path
        / "tree"
    )

    tree.mkdir(
        parents=True,
    )

    _write_cpp_tree(
        tree
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(state),
    )

    report = acquire_tree(
        tree,
        source="event-test",
        progress=lambda _message: None,
    )

    store = ChunkStore()

    event_file = (
        store.dir
        / "acquire_events.jsonl"
    )

    records = [
        json.loads(
            line
        )
        for line in event_file.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert records

    latest = records[-1]

    assert latest[
        "memory_size"
    ] == len(
        store.ids
    )

    assert latest[
        "memory_size"
    ] == report[
        "memory_size"
    ]


def test_batch_depth_is_closed_after_acquire(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = (
        tmp_path
        / "state"
    )

    tree = (
        tmp_path
        / "tree"
    )

    tree.mkdir(
        parents=True,
    )

    _write_cpp_tree(
        tree
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(state),
    )

    acquire_tree(
        tree,
        source="batch-depth-test",
        progress=lambda _message: None,
    )

    store = ChunkStore()

    assert store._batch_depth == 0
