"""Shared primitives for objective coding-contract nodes."""

from __future__ import annotations

import ast
from typing import Protocol


class CodingContract(Protocol):
    """Interface implemented by deterministic coding-contract nodes."""

    name: str
    priority: int

    def matches(
        self,
        request: str,
    ) -> bool:
        ...

    def objective_test_source(
        self,
        *,
        module_name: str,
        function_name: str,
    ) -> str | None:
        ...

    def validate_test_source(
        self,
        *,
        function_name: str,
        test_source: str,
    ) -> None:
        ...

    def red_defect_guidance(
        self,
    ) -> str:
        ...

    def preflight_constraints(
        self,
    ) -> str:
        ...

    def corrective_constraints(
        self,
        *,
        last_error: str = "",
        execution_feedback: str = "",
    ) -> str:
        ...


def _normalized_request(
    request: str,
) -> str:
    return " ".join(
        str(request or "")
        .casefold()
        .split()
    )


def _called_function_name(
    call: ast.Call,
) -> str | None:
    """Return terminal name for direct or module-qualified calls."""
    func = call.func

    if isinstance(
        func,
        ast.Name,
    ):
        return func.id

    if isinstance(
        func,
        ast.Attribute,
    ):
        return func.attr

    return None


def _literal_equality_assertions(
    *,
    function_name: str,
    test_source: str,
    argument_count: int | None = None,
) -> tuple[
    tuple[
        tuple[object, ...],
        object,
    ],
    ...,
]:
    """Extract literal ``function(...) == expected`` pytest assertions.

    Both direct calls and module-qualified calls are accepted. Dynamic
    expressions are deliberately ignored rather than assigned invented
    semantics by the harness.
    """
    try:
        tree = ast.parse(
            str(test_source or "")
        )

    except SyntaxError as error:
        raise ValueError(
            "Generated test contract is syntactically invalid"
        ) from error

    results: list[
        tuple[
            tuple[object, ...],
            object,
        ]
    ] = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Assert,
        ):
            continue

        comparison = node.test

        if not (
            isinstance(
                comparison,
                ast.Compare,
            )
            and len(
                comparison.ops
            ) == 1
            and isinstance(
                comparison.ops[0],
                ast.Eq,
            )
            and len(
                comparison.comparators
            ) == 1
        ):
            continue

        left = comparison.left
        right = comparison.comparators[0]

        call: ast.Call | None = None
        expected_node: ast.AST | None = None

        if (
            isinstance(
                left,
                ast.Call,
            )
            and _called_function_name(
                left
            )
            == function_name
        ):
            call = left
            expected_node = right

        elif (
            isinstance(
                right,
                ast.Call,
            )
            and _called_function_name(
                right
            )
            == function_name
        ):
            call = right
            expected_node = left

        if (
            call is None
            or expected_node is None
        ):
            continue

        if (
            argument_count is not None
            and len(
                call.args
            )
            != argument_count
        ):
            continue

        try:
            arguments = tuple(
                ast.literal_eval(
                    argument
                )
                for argument in call.args
            )

            expected = ast.literal_eval(
                expected_node
            )

        except (
            ValueError,
            TypeError,
        ):
            # Dynamic expressions remain subject to runtime pytest truth.
            continue

        results.append(
            (
                arguments,
                expected,
            )
        )

    return tuple(
        results
    )


def _numeric_list_equality_assertions(
    *,
    function_name: str,
    test_source: str,
) -> tuple[
    tuple[
        list[int | float] | tuple[int | float, ...],
        list[object] | tuple[object, ...],
    ],
    ...,
]:
    """Extract literal one-argument numeric-list equality assertions.

    This helper owns only structural/type facts shared by list-oriented
    contracts. It deliberately does not assign sorting, uniqueness, order,
    or other domain semantics.
    """
    assertions = _literal_equality_assertions(
        function_name=function_name,
        test_source=test_source,
        argument_count=1,
    )

    results: list[
        tuple[
            list[int | float] | tuple[int | float, ...],
            list[object] | tuple[object, ...],
        ]
    ] = []

    for arguments, expected in assertions:
        (
            values,
        ) = arguments

        if not isinstance(
            values,
            (list, tuple),
        ):
            continue

        if not isinstance(
            expected,
            (list, tuple),
        ):
            continue

        if not all(
            isinstance(
                value,
                (int, float),
            )
            and not isinstance(
                value,
                bool,
            )
            for value in values
        ):
            continue

        results.append(
            (
                values,
                expected,
            )
        )

    return tuple(
        results
    )
