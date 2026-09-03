from __future__ import annotations

import ast
from pathlib import Path


TUI = Path(
    "src/sophyane/tui_v2.py"
)


def _run_function():
    text = TUI.read_text()
    tree = ast.parse(text)

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "run_observable_tui"
        ):
            return text, node

    raise AssertionError(
        "run_observable_tui() missing"
    )


def _branches():
    text, function = _run_function()

    for node in ast.walk(function):
        if not isinstance(
            node,
            ast.If,
        ):
            continue

        test = node.test

        if not (
            isinstance(test, ast.Compare)
            and isinstance(
                test.left,
                ast.Name,
            )
            and test.left.id
            == "session_mode"
        ):
            continue

        current = node
        mode2 = None

        while True:
            check = current.test

            if (
                isinstance(
                    check,
                    ast.Compare,
                )
                and isinstance(
                    check.left,
                    ast.Name,
                )
                and check.left.id
                == "session_mode"
                and len(
                    check.comparators
                )
                == 1
                and isinstance(
                    check.comparators[0],
                    ast.Constant,
                )
                and check.comparators[0].value
                == "sli_graph"
            ):
                mode2 = current.body

            if (
                len(current.orelse)
                == 1
                and isinstance(
                    current.orelse[0],
                    ast.If,
                )
            ):
                current = current.orelse[0]
                continue

            if mode2 is not None:
                return (
                    text,
                    mode2,
                    current.orelse,
                )

            break

    raise AssertionError(
        "session_mode branch containing sli_graph missing"
    )



def _calls(nodes):
    result = []

    for root in nodes:
        for node in ast.walk(root):
            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            if isinstance(
                node.func,
                ast.Name,
            ):
                result.append(
                    node.func.id
                )

            elif isinstance(
                node.func,
                ast.Attribute,
            ):
                result.append(
                    node.func.attr
                )

    return result


def test_mode2_has_explicit_top_level_authority():
    text = TUI.read_text()

    assert (
        text.count(
            "SOPHYANE_MODE2_SLI_TOP_LEVEL_AUTHORITY_V1"
        )
        == 1
    )

    assert (
        text.count(
            'elif session_mode == "sli_graph":'
        )
        == 1
    )


def test_mode2_calls_sli_graph_directly():
    _text, mode2, _provider = (
        _branches()
    )

    assert mode2 is not None

    calls = _calls(
        mode2
    )

    assert (
        "run_sli_graph"
        in calls
    )


def test_mode2_does_not_construct_llm_authority():
    _text, mode2, _provider = (
        _branches()
    )

    assert mode2 is not None

    calls = _calls(
        mode2
    )

    assert (
        "SophyaneAgent"
        not in calls
    )

    assert (
        "create_provider"
        not in calls
    )

    assert (
        "_create_provider_for_observable_tui"
        not in calls
    )


def test_explicit_llm_modes_remain_provider_backed():
    _text, _mode2, provider = (
        _branches()
    )

    calls = _calls(
        provider
    )

    assert (
        "SophyaneAgent"
        in calls
    )

    assert (
        "create_provider"
        in calls
        or "_create_provider_for_observable_tui"
        in calls
    )
