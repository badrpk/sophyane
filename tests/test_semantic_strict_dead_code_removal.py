from __future__ import annotations

from pathlib import Path
import ast
import inspect

import sophyane.sli_semantic_intelligence as semantic


STRICT_HELPERS = {
    "_strict_normalize_language",
    "_strict_chunk_text",
    "_strict_chunk_path",
    "_strict_is_disallowed_chunk",
    "_strict_is_framework_internal",
    "_strict_allowed_languages",
    "_strict_signal_count",
    "_strict_minimum_signals",
}


def test_strict_retrieval_generation_is_absent():
    path = Path(
        "src/sophyane/sli_semantic_intelligence.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(text)

    functions = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }

    assert not (
        STRICT_HELPERS
        & functions
    )

    assert "_STRICT_SIGNALS" not in text


def test_final_retrieval_policy_remains_active():
    source = inspect.getsource(
        semantic.retrieve_for_capability
    )

    assert "_final_compatible" in source

    for obsolete in STRICT_HELPERS:
        assert obsolete not in source

    assert "score += 2.0" not in source
    assert "signal_count * 0.65" not in source


def test_semantic_plan_retrieval_still_delegates():
    source = inspect.getsource(
        semantic.retrieve_semantic_plan
    )

    assert (
        "retrieve_for_capability("
        in source
    )

    assert "_final_compatible(" not in source


def test_single_semantic_public_definitions_remain():
    path = Path(
        "src/sophyane/sli_semantic_intelligence.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        )
    )

    for name in (
        "build_semantic_plan",
        "retrieve_for_capability",
        "retrieve_semantic_plan",
    ):
        count = sum(
            1
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name == name
            )
        )

        assert count == 1
