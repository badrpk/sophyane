from __future__ import annotations

import ast
import inspect
from pathlib import Path

import sophyane.code_memory.internet_acquire as internet


def _source() -> str:
    return Path(
        "src/sophyane/code_memory/internet_acquire.py"
    ).read_text(
        encoding="utf-8",
    )


def test_one_base_search_definition_remains():
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
            == "search_repositories"
        )
    ]

    assert len(nodes) == 1

    assert (
        "_sli_search_before_v5"
        not in text
    )

    assert (
        "_sli_search_repos_before_v8"
        not in text
    )


def test_strict_guard_wraps_consolidated_search_directly():
    strict = (
        internet.search_repositories
    )

    assert (
        strict.__module__
        == "sophyane.code_memory.strict_acquisition_guard"
    )

    closure = inspect.getclosurevars(
        strict
    )

    base = closure.nonlocals[
        "original_search"
    ]

    assert (
        base.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    source = inspect.getsource(
        base
    )

    assert (
        "_sli_search_before_v5"
        not in source
    )

    assert (
        "_sli_search_repos_before_v8"
        not in source
    )

    assert (
        "build_search_queries("
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


def test_runtime_query_upgrade_is_still_used():
    assert (
        internet._queries
        is internet.build_search_queries
    )

    assert (
        internet.build_search_queries.__module__
        == "sophyane.code_memory.acquisition_intelligence"
    )


def test_strict_search_has_single_function_boundary():
    strict = (
        internet.search_repositories
    )

    closure = inspect.getclosurevars(
        strict
    )

    base = closure.nonlocals[
        "original_search"
    ]

    # The strict wrapper should point directly at the
    # consolidated internet_acquire implementation.
    assert (
        base.__name__
        == "search_repositories"
    )

    assert (
        base.__qualname__
        == "search_repositories"
    )
