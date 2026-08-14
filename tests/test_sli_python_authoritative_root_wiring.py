from pathlib import Path
from types import SimpleNamespace

import pytest

import sophyane.sli_capability_engine as engine
import sophyane.code_memory.generator as generator
import sophyane.code_memory.compose as compose


def match(chunk_id: str, score: float = 1.0):
    return SimpleNamespace(
        chunk_id=chunk_id,
        score=score,
    )


def requirement(name: str):
    return SimpleNamespace(
        name=name,
        covered=True,
        selected_ids=[],
    )


def plan(*names: str):
    return SimpleNamespace(
        capabilities=[
            requirement(name)
            for name in names
        ],
    )


def test_authoritative_roots_use_best_match_per_capability():
    semantic_plan = plan(
        "logs",
        "ports",
        "process",
        "commands",
    )

    semantic_matches = {
        "logs": [
            match("log-1", 9.0),
            match("log-2", 8.0),
        ],
        "ports": [
            match("port-1", 8.5),
            match("port-2", 7.5),
        ],
        "process": [
            match("proc-1", 8.2),
            match("proc-2", 7.2),
        ],
        "commands": [
            match("cmd-1", 8.1),
            match("cmd-2", 7.1),
        ],
    }

    roots = engine._capability_authoritative_root_ids(
        semantic_plan,
        semantic_matches,
    )

    assert roots == [
        "log-1",
        "port-1",
        "proc-1",
        "cmd-1",
    ]


def test_authoritative_roots_stably_deduplicate_shared_winner():
    semantic_plan = plan(
        "first",
        "second",
        "third",
    )

    semantic_matches = {
        "first": [
            match("shared", 9.0),
            match("first-backup", 8.0),
        ],
        "second": [
            match("shared", 8.8),
            match("second-backup", 8.0),
        ],
        "third": [
            match("third-root", 8.5),
        ],
    }

    roots = engine._capability_authoritative_root_ids(
        semantic_plan,
        semantic_matches,
    )

    assert roots == [
        "shared",
        "third-root",
    ]


def test_generator_forwards_candidates_and_roots(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_compose(
        message,
        workspace,
        *,
        store=None,
        progress=None,
        selected_ids=None,
        root_ids=None,
    ):
        captured["message"] = message
        captured["selected_ids"] = selected_ids
        captured["root_ids"] = root_ids

        return (
            "FORWARD_OK",
            list(root_ids or []),
        )

    monkeypatch.setattr(
        generator,
        "compose_from_request",
        fake_compose,
    )

    result = generator.generate_from_request(
        "generic software request",
        tmp_path,
        selected_ids=[
            "root-a",
            "candidate-a2",
            "root-b",
            "candidate-b2",
        ],
        root_ids=[
            "root-a",
            "root-b",
        ],
    )

    assert result == (
        "FORWARD_OK",
        [
            "root-a",
            "root-b",
        ],
    )

    assert captured["selected_ids"] == [
        "root-a",
        "candidate-a2",
        "root-b",
        "candidate-b2",
    ]

    assert captured["root_ids"] == [
        "root-a",
        "root-b",
    ]


def test_compose_forwards_roots_into_python_assembler(
    monkeypatch,
    tmp_path: Path,
):
    candidate_a = SimpleNamespace(
        id="root-a",
        text="def a():\n    return 1\n",
        path="/repo/a.py::a",
        language="python",
        meta={},
    )

    candidate_b = SimpleNamespace(
        id="candidate-b",
        text="def b():\n    return 2\n",
        path="/repo/b.py::b",
        language="python",
        meta={},
    )

    store = SimpleNamespace(
        chunks={
            "root-a": candidate_a,
            "candidate-b": candidate_b,
        },
    )

    captured = {}

    def fake_python_compose(
        chunks,
        *,
        root_ids=None,
    ):
        captured["chunk_ids"] = [
            chunk.id
            for chunk in chunks
        ]
        captured["root_ids"] = root_ids

        return (
            "def assembled():\n    return 1\n",
            list(root_ids or []),
        )

    monkeypatch.setattr(
        compose,
        "compose_python_from_chunks",
        fake_python_compose,
    )

    report, used = compose.compose_from_request(
        "Build a Python CLI tool.",
        tmp_path,
        store=store,
        selected_ids=[
            "root-a",
            "candidate-b",
        ],
        root_ids=[
            "root-a",
        ],
    )

    assert captured["chunk_ids"] == [
        "root-a",
        "candidate-b",
    ]

    assert captured["root_ids"] == [
        "root-a",
    ]

    assert used == [
        "root-a",
    ]

    assert (
        tmp_path / "main.py"
    ).is_file()


def test_authoritative_root_helper_handles_missing_plan():
    assert (
        engine._capability_authoritative_root_ids(
            None,
            {},
        )
        == []
    )
