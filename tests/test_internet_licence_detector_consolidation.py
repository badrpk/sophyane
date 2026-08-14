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


def test_one_base_licence_detector_remains():
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
            == "_detected_licence"
        )
    ]

    assert len(nodes) == 1

    assert (
        "_sli_licence_before_v5"
        not in text
    )

    source = ast.get_source_segment(
        text,
        nodes[0],
    )

    assert source is not None

    assert (
        "_sli_detect_lic_v8"
        in source
    )

    assert (
        "_SLI_PERMISSIVE_V8"
        in source
    )

    assert (
        "_sli_lic_decide_v8"
        in source
    )


def test_strict_guard_wraps_base_detector_directly():
    public = (
        internet._detected_licence
    )

    assert (
        public.__module__
        == "sophyane.code_memory.strict_acquisition_guard"
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "wrapped"
    ]

    assert (
        base.__module__
        == "sophyane.code_memory.internet_acquire"
    )

    assert (
        base.__name__
        == "_detected_licence"
    )

    assert (
        base.__qualname__
        == "_detected_licence"
    )

    source = inspect.getsource(
        base
    )

    assert (
        "_sli_licence_before_v5"
        not in source
    )

    assert (
        "_sli_detect_lic_v8"
        in source
    )


def test_no_acquisition_intelligence_detector_layer_remains():
    public = (
        internet._detected_licence
    )

    closure = inspect.getclosurevars(
        public
    )

    base = closure.nonlocals[
        "wrapped"
    ]

    assert (
        base.__module__
        != "sophyane.code_memory.acquisition_intelligence"
    )


def test_strict_detector_is_outer_policy():
    public = (
        internet._detected_licence
    )

    closure = inspect.getclosurevars(
        public
    )

    assert (
        "wrapped"
        in closure.nonlocals
    )

    assert (
        "strict_licence_result"
        in closure.globals
    )
