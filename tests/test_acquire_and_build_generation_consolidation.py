from __future__ import annotations

from pathlib import Path
import ast
import inspect

import sophyane.code_memory.internet_acquire as internet


def _source():
    return Path(
        "src/sophyane/code_memory/internet_acquire.py"
    ).read_text(
        encoding="utf-8",
    )


def test_one_base_acquire_and_build_remains():
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
            == "acquire_and_build"
        )
    ]

    assert len(nodes) == 1

    assert (
        "_acquire_and_build_before_relevance_guard"
        not in text
    )


def test_consolidated_build_contains_both_policies():
    public = (
        internet.acquire_and_build
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "original_build"
    ]

    source = inspect.getsource(
        base
    )

    for marker in (
        "acquire_for_request(",
        "_sli_artifact_matches_request(",
        "_sli_request_identity_terms(",
        "preview_sli_artifact",
        "artifact.unlink(",
    ):
        assert marker in source


def test_strict_guard_wraps_consolidated_build_directly():
    public = (
        internet.acquire_and_build
    )

    assert (
        public.__module__
        == "sophyane.code_memory.strict_acquisition_guard"
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "original_build"
    ]

    assert (
        base.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    assert (
        base.__qualname__
        == "acquire_and_build"
    )


def test_base_build_uses_active_acquire_for_request():
    closure = inspect.getclosurevars(
        internet.acquire_and_build
    )

    base = closure.nonlocals[
        "original_build"
    ]

    assert (
        base.__globals__[
            "acquire_for_request"
        ]
        is internet.acquire_for_request
    )
