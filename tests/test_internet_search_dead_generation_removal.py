from __future__ import annotations

from pathlib import Path
import ast
import inspect

import sophyane.code_memory.internet_acquire as internet


def test_only_consolidated_base_search_remains():
    path = Path(
        "src/sophyane/code_memory/internet_acquire.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

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
            == "search_repositories"
        )
    ]

    assert len(nodes) == 1

    # All historical search snapshot generations are gone.
    for obsolete in (
        "_search_repositories_before_semantic_rank",
        "_search_repositories_before_identity_v4",
        "_sli_search_before_v5",
        "_sli_search_repos_before_v8",
    ):
        assert obsolete not in text

    source = ast.get_source_segment(
        text,
        nodes[0],
    )

    assert source is not None

    # Consolidated base search owns the formerly layered policies.
    assert "build_search_queries(" in source

    assert (
        "_sli_repository_identity_score_v4("
        in source
    )

    assert (
        "_sli_cached_repositories_v5("
        in source
    )

    assert (
        '"_sli_sort_repos_v8"'
        in source
    )


def test_public_search_uses_strict_consolidated_chain():
    strict = internet.search_repositories

    strict_closure = inspect.getclosurevars(
        strict
    )

    base = strict_closure.nonlocals[
        "original_search"
    ]

    assert (
        strict.__module__
        == "sophyane.code_memory.strict_acquisition_guard"
    )

    assert callable(
        base
    )

    assert (
        base.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    assert (
        base.__name__
        == "search_repositories"
    )

    assert (
        base.__qualname__
        == "search_repositories"
    )

    source = inspect.getsource(
        base
    )

    # No historical search-wrapper hop remains.
    assert (
        "_sli_search_before_v5"
        not in source
    )

    assert (
        "_sli_search_repos_before_v8"
        not in source
    )

    # Base implementation directly contains final search behavior.
    assert "build_search_queries(" in source

    assert (
        "_sli_cached_repositories_v5("
        in source
    )

    assert (
        '"_sli_sort_repos_v8"'
        in source
    )

    # Query policy remains the acquisition-intelligence upgrade.
    assert (
        base.__globals__[
            "build_search_queries"
        ]
        is internet.build_search_queries
    )


def test_query_patch_still_captures_both_fallback_builders():
    query = internet.build_search_queries

    closure = inspect.getclosurevars(
        query
    )

    original_queries = (
        closure.nonlocals[
            "original_queries"
        ]
    )

    original_public = (
        closure.nonlocals[
            "original_public_queries"
        ]
    )

    assert callable(
        original_queries
    )

    assert callable(
        original_public
    )

    assert (
        original_queries.__name__
        == "_queries"
    )

    assert (
        original_public.__name__
        == "build_search_queries"
    )


def test_queries_and_public_builder_still_share_upgrade():
    assert (
        internet._queries
        is internet.build_search_queries
    )

    assert (
        internet._queries.__module__
        == "sophyane.code_memory.acquisition_intelligence"
    )
