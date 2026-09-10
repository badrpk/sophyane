from __future__ import annotations

import ast
import inspect
import textwrap

import sophyane.providers.fallback as fallback


def _membership_contains(
    source: str,
    *,
    variable: str,
    required: set[str],
) -> bool:
    tree = ast.parse(
        textwrap.dedent(source)
    )

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Compare,
        ):
            continue

        if len(node.ops) != 1:
            continue

        if not isinstance(
            node.ops[0],
            ast.In,
        ):
            continue

        if not (
            isinstance(
                node.left,
                ast.Name,
            )
            and node.left.id == variable
        ):
            continue

        if len(node.comparators) != 1:
            continue

        container = node.comparators[0]

        if not isinstance(
            container,
            (
                ast.Set,
                ast.List,
                ast.Tuple,
            ),
        ):
            continue

        values = {
            item.value
            for item in container.elts
            if (
                isinstance(
                    item,
                    ast.Constant,
                )
                and isinstance(
                    item.value,
                    str,
                )
            )
        }

        if required.issubset(values):
            return True

    return False


def test_cloud_session_overrides_persisted_fallback_order() -> None:
    source = inspect.getsource(
        fallback.build_fallback_provider
    )

    assert (
        "SOPHYANE_STRICT_CLOUD_PROVIDER_CHAIN_V1"
        in source
    )

    assert _membership_contains(
        source,
        variable="session_mode",
        required={
            "cloud_llm",
            "nifdu_llm",
        },
    )

    assert (
        "order = ["
        in source
    )


def test_cloud_session_blocks_bootstrap_local_rescue() -> None:
    source = inspect.getsource(
        fallback.FallbackProvider.generate
    )

    assert (
        "SOPHYANE_STRICT_CLOUD_BOOTSTRAP_BOUNDARY_V2"
        in source
    )

    assert _membership_contains(
        source,
        variable="session_mode",
        required={
            "cloud_llm",
            "nifdu_llm",
        },
    )

    assert (
        "SOPHYANE_DISABLE_LOCAL_FALLBACK"
        in source
    )

    assert (
        "and not strict_cloud"
        in source
    )
