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


def test_one_base_public_query_builder_remains():
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
            == "build_search_queries"
        )
    ]

    assert len(nodes) == 1

    source = ast.get_source_segment(
        text,
        nodes[0],
    )

    assert source is not None

    for marker in (
        "_sli_identity_v5",
        "cpp_request",
        "python_request",
        "rust_request",
        "browser_request",
    ):
        assert marker in source


def test_legacy_queries_fallback_remains_once():
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
            == "_queries"
        )
    ]

    assert len(nodes) == 1


def test_acquisition_intelligence_captures_correct_builders():
    active = (
        internet.build_search_queries
    )

    closure = inspect.getclosurevars(
        active
    )

    legacy = closure.nonlocals[
        "original_queries"
    ]

    base = closure.nonlocals[
        "original_public_queries"
    ]

    assert (
        legacy.__name__
        == "_queries"
    )

    assert (
        legacy.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    assert (
        base.__name__
        == "build_search_queries"
    )

    assert (
        base.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    source = inspect.getsource(
        base
    )

    assert (
        "_sli_identity_v5"
        in source
    )

    assert (
        "python_request"
        in source
    )

    assert (
        "rust_request"
        in source
    )


def test_public_query_aliases_remain_upgraded_policy():
    assert (
        internet._queries
        is internet.build_search_queries
    )

    assert (
        internet.build_search_queries.__module__
        == "sophyane.code_memory.acquisition_intelligence"
    )


def test_consolidated_search_resolves_upgraded_builder():
    strict = (
        internet.search_repositories
    )

    closure = inspect.getclosurevars(
        strict
    )

    base = closure.nonlocals[
        "original_search"
    ]

    assert (
        base.__globals__[
            "build_search_queries"
        ]
        is internet.build_search_queries
    )
