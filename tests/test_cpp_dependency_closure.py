from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sophyane.code_memory.chunker import (
    _lang,
    iter_source_files,
)

import sophyane.code_memory.compose as compose


@dataclass
class FakeChunk:
    id: str
    language: str
    text: str
    path: str


def test_cpp_extension_family(tmp_path: Path):
    suffixes = (
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hpp",
        ".hh",
        ".hxx",
    )

    for suffix in suffixes:
        path = tmp_path / ("file" + suffix)

        path.write_text(
            "int example_symbol = 1;\n" * 5,
            encoding="utf-8",
        )

        assert _lang(path) == "cpp"

    enumerated = {
        path.suffix
        for path in iter_source_files(
            tmp_path
        )
    }

    for suffix in suffixes:
        assert suffix in enumerated


def test_cpp_recursive_header_closure(tmp_path: Path):
    repo = tmp_path / "repo"

    src = repo / "src"
    include = repo / "include"

    src.mkdir(parents=True)
    include.mkdir(parents=True)

    main = src / "main.cpp"
    engine = include / "engine.hpp"
    model = include / "model.hpp"

    main.write_text(
        '#include "engine.hpp"\n'
        "int main() { Engine e; return e.value(); }\n",
        encoding="utf-8",
    )

    engine.write_text(
        '#include "model.hpp"\n'
        "struct Engine { "
        "int value() const { return Model{}.value; } "
        "};\n",
        encoding="utf-8",
    )

    model.write_text(
        "struct Model { int value = 7; };\n",
        encoding="utf-8",
    )

    chunks = [
        FakeChunk(
            id="main",
            language="cpp",
            text=main.read_text(),
            path=str(main),
        ),
        FakeChunk(
            id="engine",
            language="cpp",
            text=engine.read_text(),
            path=str(engine),
        ),
        FakeChunk(
            id="model",
            language="cpp",
            text=model.read_text(),
            path=str(model),
        ),
    ]

    (
        source,
        used,
        repository_root,
        closure,
        errors,
    ) = compose._compose_cpp_with_closure(
        chunks
    )

    assert source is not None
    assert errors == []
    assert repository_root == repo.resolve()

    assert used == [
        "main",
        "engine",
        "model",
    ]

    closure_paths = {
        Path(chunk.path).name
        for chunk in closure
    }

    assert closure_paths == {
        "main.cpp",
        "engine.hpp",
        "model.hpp",
    }


def test_materialized_closure_compiles(tmp_path: Path):
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"

    src = repo / "src"
    include = repo / "include"

    src.mkdir(parents=True)
    include.mkdir(parents=True)

    main = src / "main.cpp"
    engine = include / "engine.hpp"

    main.write_text(
        '#include "engine.hpp"\n'
        "int main() { Engine e; return e.run(); }\n",
        encoding="utf-8",
    )

    engine.write_text(
        "struct Engine { "
        "int run() const { return 0; } "
        "};\n",
        encoding="utf-8",
    )

    chunks = [
        FakeChunk(
            id="main",
            language="cpp",
            text=main.read_text(),
            path=str(main),
        ),
        FakeChunk(
            id="engine",
            language="cpp",
            text=engine.read_text(),
            path=str(engine),
        ),
    ]

    (
        _source,
        _used,
        repository_root,
        closure,
        errors,
    ) = compose._compose_cpp_with_closure(
        chunks
    )

    assert errors == []

    written = compose._materialize_cpp_closure(
        workspace,
        repository_root=repository_root,
        chunks=closure,
    )

    assert written

    validation = compose._validate_cpp_workspace(
        workspace / "src" / "main.cpp",
        workspace=workspace,
    )

    assert validation == []


def test_missing_header_is_reported(tmp_path: Path):
    repo = tmp_path / "repo"
    src = repo / "src"

    src.mkdir(parents=True)

    main = src / "main.cpp"

    main.write_text(
        '#include "missing.hpp"\n'
        "int main() { return 0; }\n",
        encoding="utf-8",
    )

    chunks = [
        FakeChunk(
            id="main",
            language="cpp",
            text=main.read_text(),
            path=str(main),
        ),
    ]

    (
        _source,
        _used,
        _root,
        _closure,
        errors,
    ) = compose._compose_cpp_with_closure(
        chunks
    )

    assert errors
    assert "unresolved quoted include" in errors[0]


def test_short_non_entry_cpp_fragment_is_still_rejected(
    tmp_path: Path,
) -> None:
    fragment = tmp_path / "fragment.cpp"

    fragment.write_text(
        "struct Tiny { int value; };\n",
        encoding="utf-8",
    )

    chunk = FakeChunk(
        id="tiny",
        language="cpp",
        text=fragment.read_text(),
        path=str(fragment),
    )

    (
        source,
        used,
        repository_root,
        closure,
        errors,
    ) = compose._compose_cpp_with_closure(
        [chunk]
    )

    assert source is None
    assert used == []
    assert repository_root is None
    assert closure == []
    assert errors == [
        "no compatible C++ implementation chunk found"
    ]
