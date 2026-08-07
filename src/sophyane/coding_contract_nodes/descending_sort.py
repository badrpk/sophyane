"""Descending-sort objective coding contract."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .base import (
    _called_function_name,
    _normalized_request,
)


@dataclass(frozen=True)
class DescendingSortContract:
    """Deterministic contract for descending numeric-list sorting."""

    name: str = "descending_sort"
    priority: int = 200

    def matches(
        self,
        request: str,
    ) -> bool:
        request_text = _normalized_request(
            request
        )

        return (
            (
                "sort" in request_text
                or "sorted" in request_text
                or "order" in request_text
            )
            and (
                "descending" in request_text
                or "descending order" in request_text
            )
        )

    def objective_test_source(
        self,
        *,
        module_name: str,
        function_name: str,
    ) -> str:
        return (
            f"from {module_name} import {function_name}\n"
            "\n"
            "def test_objective_descending_unsorted():\n"
            f"    assert {function_name}([1, 9, 2, 5]) == [9, 5, 2, 1]\n"
            "\n"
            "def test_objective_descending_duplicates():\n"
            f"    assert {function_name}([3, 1, 3, 2]) == [3, 3, 2, 1]\n"
        )

    def validate_test_source(
        self,
        *,
        function_name: str,
        test_source: str,
    ) -> None:
        try:
            tree = ast.parse(
                str(test_source or "")
            )
        except SyntaxError as error:
            raise ValueError(
                "Generated test contract is syntactically invalid"
            ) from error

        checked = 0
        discriminates_from_identity = False

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
                and len(comparison.ops) == 1
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
                or len(call.args) != 1
            ):
                continue

            try:
                values = ast.literal_eval(
                    call.args[0]
                )
                expected = ast.literal_eval(
                    expected_node
                )
            except (
                ValueError,
                TypeError,
            ):
                continue

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

            actual = sorted(
                values,
                reverse=True,
            )

            checked += 1

            if list(values) != actual:
                discriminates_from_identity = True

            if list(expected) != actual:
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "descending-sort request: "
                    f"{function_name}({values!r}) should equal "
                    f"{actual!r}, but the generated test expects "
                    f"{expected!r}."
                )

        if (
            checked > 0
            and not discriminates_from_identity
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT descending-sort "
                "request, but its literal examples are non-discriminating: "
                "the input is already descending. Include at least one ordinary "
                "unsorted literal input."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect descending-sort implementation is "
            "to sort the values in ascending order instead.\n"
            "- Preserve duplicates so the defect is specifically ordering direction.\n"
            "- Prefer a wrong returned list over crashes or syntax errors."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- This task requires descending-order sorting.\n"
            "- Include at least one ordinary unsorted literal input.\n"
            "- Objective witness: [1, 9, 2, 5] must become [9, 5, 2, 1].\n"
            "- Preserve duplicates."
        )

    def corrective_constraints(
        self,
        *,
        last_error: str = "",
        execution_feedback: str = "",
    ) -> str:
        combined = (
            str(last_error or "")
            + "\n"
            + str(execution_feedback or "")
        ).lower()

        constraints: list[str] = []

        if (
            "non-discriminating"
            in combined
            or "already descending"
            in combined
        ):
            constraints.extend(
                [
                    (
                        "Use an ordinary unsorted literal input so an identity "
                        "implementation cannot accidentally pass."
                    ),
                    (
                        "Objective witness: [1, 9, 2, 5] must become "
                        "[9, 5, 2, 1]."
                    ),
                ]
            )

        if (
            "contradicts the current"
            in combined
            and "descending-sort"
            in combined
        ):
            constraints.append(
                "Recompute the expected output using descending ordering "
                "from the CURRENT request."
            )

        if (
            "passed every generated pytest test"
            in combined
            or "test suite was non-discriminating"
            in combined
        ):
            constraints.append(
                "At least one ordinary descending-sort assertion MUST fail "
                "against the deliberately defective implementation."
            )

        if not constraints:
            return ""

        unique: list[str] = []

        for constraint in constraints:
            if constraint not in unique:
                unique.append(
                    constraint
                )

        return (
            "OBJECTIVE CORRECTIVE CONSTRAINTS FOR THIS RETRY:\n"
            + "\n".join(
                f"- {constraint}"
                for constraint in unique
            )
        )
