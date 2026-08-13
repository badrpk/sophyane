from types import SimpleNamespace

import pytest

import sophyane.sli_capability_engine as engine


def row(chunk_id):
    return SimpleNamespace(
        chunk_id=chunk_id,
    )


def requirement(name):
    return SimpleNamespace(
        name=name,
    )


def plan(*names):
    return SimpleNamespace(
        capabilities=[
            requirement(name)
            for name in names
        ],
    )


def test_capability_preserving_flatten_interleaves_ranked_evidence():
    semantic_plan = plan(
        "logs",
        "ports",
        "processes",
    )

    semantic_matches = {
        "logs": [
            row("log-1"),
            row("log-2"),
            row("log-3"),
        ],
        "ports": [
            row("port-1"),
            row("port-2"),
            row("port-3"),
        ],
        "processes": [
            row("proc-1"),
            row("proc-2"),
            row("proc-3"),
        ],
    }

    selected = engine._capability_preserving_selected_ids(
        semantic_plan,
        semantic_matches,
    )

    assert selected == [
        "log-1",
        "port-1",
        "proc-1",
        "log-2",
        "port-2",
        "proc-2",
        "log-3",
        "port-3",
        "proc-3",
    ]


def test_capability_preserving_flatten_stably_deduplicates():
    semantic_plan = plan(
        "first",
        "second",
        "third",
    )

    semantic_matches = {
        "first": [
            row("shared"),
            row("first-only"),
        ],
        "second": [
            row("shared"),
            row("second-only"),
        ],
        "third": [
            row("third-only"),
            row("shared"),
        ],
    }

    selected = engine._capability_preserving_selected_ids(
        semantic_plan,
        semantic_matches,
    )

    assert selected == [
        "shared",
        "third-only",
        "first-only",
        "second-only",
    ]


def test_capability_preserving_flatten_skips_empty_ids():
    semantic_plan = plan(
        "a",
        "b",
    )

    semantic_matches = {
        "a": [
            row(""),
            row("a-2"),
        ],
        "b": [
            row("b-1"),
        ],
    }

    selected = engine._capability_preserving_selected_ids(
        semantic_plan,
        semantic_matches,
    )

    assert selected == [
        "b-1",
        "a-2",
    ]


def test_capability_preserving_flatten_handles_missing_rows():
    semantic_plan = plan(
        "a",
        "missing",
        "b",
    )

    semantic_matches = {
        "a": [row("a-1")],
        "b": [row("b-1")],
    }

    selected = engine._capability_preserving_selected_ids(
        semantic_plan,
        semantic_matches,
    )

    assert selected == [
        "a-1",
        "b-1",
    ]


def test_capability_preserving_flatten_handles_none_plan():
    assert (
        engine._capability_preserving_selected_ids(
            None,
            {},
        )
        == []
    )
