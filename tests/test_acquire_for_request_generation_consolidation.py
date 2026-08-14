from __future__ import annotations

from pathlib import Path
import ast
import inspect

import sophyane.code_memory.internet_acquire as internet


def _source() -> str:
    return Path(
        "src/sophyane/code_memory/internet_acquire.py"
    ).read_text(
        encoding="utf-8",
    )


def test_single_base_acquire_for_request_remains():
    text = _source()

    tree = ast.parse(
        text
    )

    nodes = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "acquire_for_request"
        )
    ]

    assert len(nodes) == 1

    assert (
        "_acquire_for_request_before_semantic_rank"
        not in text
    )


def test_base_contains_acquisition_and_semantic_ranking():
    public = (
        internet.acquire_for_request
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "original_acquire"
    ]

    source = inspect.getsource(
        base
    )

    for marker in (
        "search_repositories(",
        "clone_repository(",
        "_detected_licence(",
        "_browser_files(",
        "_ingest(",
        "_evaluate(",
        "_sli_repository_root(",
        "_sli_candidate_semantic_score(",
        "matched_identity",
        "EVENTS.open(",
    ):
        assert marker in source


def test_acquisition_intelligence_wraps_base_directly():
    public = (
        internet.acquire_for_request
    )

    assert (
        public.__module__
        == "sophyane.code_memory.acquisition_intelligence"
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "original_acquire"
    ]

    assert (
        base.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    assert (
        base.__name__
        == "acquire_for_request"
    )

    assert (
        base.__qualname__
        == "acquire_for_request"
    )


def test_build_resolves_active_acquire_dynamically():
    strict_build = (
        internet.acquire_and_build
    )

    closure = inspect.getclosurevars(
        strict_build
    )

    base_build = closure.nonlocals[
        "original_build"
    ]

    assert (
        base_build.__globals__[
            "acquire_for_request"
        ]
        is internet.acquire_for_request
    )


def test_final_base_return_contract_is_present():
    public = (
        internet.acquire_for_request
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "original_acquire"
    ]

    source = inspect.getsource(
        base
    )

    for marker in (
        '"event"',
        '"best_document"',
        '"best_score"',
        '"best_issues"',
    ):
        assert marker in source
