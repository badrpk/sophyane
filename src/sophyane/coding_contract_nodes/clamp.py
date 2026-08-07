"""Clamp objective coding contract."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .base import (
    _called_function_name,
    _normalized_request,
)


@dataclass(frozen=True)
class ClampContract:
    """Clamp one numeric value to an inclusive lower/upper bound."""

    name: str = "clamp"
    priority: int = 100

    def matches(
        self,
        request: str,
    ) -> bool:
        request_text = _normalized_request(
            request
        )

        return (
            "clamp" in request_text
            and (
                "lower" in request_text
                or "minimum" in request_text
                or "min" in request_text
            )
            and (
                "upper" in request_text
                or "maximum" in request_text
                or "max" in request_text
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
            "def test_objective_clamp_below_lower():\n"
            f"    assert {function_name}(-5, 0, 10) == 0\n"
            "\n"
            "def test_objective_clamp_inside_range():\n"
            f"    assert {function_name}(6, 0, 10) == 6\n"
            "\n"
            "def test_objective_clamp_above_upper():\n"
            f"    assert {function_name}(14, 0, 10) == 10\n"
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
        covers_lower = False
        covers_inside = False
        covers_upper = False

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
                or len(
                    call.args
                ) != 3
            ):
                continue

            try:
                value = ast.literal_eval(
                    call.args[0]
                )
                lower = ast.literal_eval(
                    call.args[1]
                )
                upper = ast.literal_eval(
                    call.args[2]
                )
                expected = ast.literal_eval(
                    expected_node
                )

            except (
                ValueError,
                TypeError,
            ):
                continue

            items = (
                value,
                lower,
                upper,
                expected,
            )

            if not all(
                isinstance(
                    item,
                    (int, float),
                )
                and not isinstance(
                    item,
                    bool,
                )
                for item in items
            ):
                continue

            if lower > upper:
                continue

            actual = max(
                lower,
                min(
                    value,
                    upper,
                ),
            )

            checked += 1

            if value < lower:
                covers_lower = True
            elif value > upper:
                covers_upper = True
            else:
                covers_inside = True

            if actual != expected:
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "clamp request: "
                    f"{function_name}({value!r}, {lower!r}, {upper!r}) "
                    f"should equal {actual!r}, but the generated "
                    f"test expects {expected!r}."
                )

        if checked > 0 and not (
            covers_lower
            and covers_inside
            and covers_upper
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT clamp request, "
                "but its literal examples are non-discriminating: include "
                "one value below the lower bound, one inside the range, "
                "and one above the upper bound."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect clamp implementation may apply "
            "only the upper bound and fail to enforce the lower bound.\n"
            "- Keep in-range and upper-bound behavior plausible so the defect "
            "is specifically the missing lower-bound clamp.\n"
            "- Prefer a wrong returned value over crashes or syntax errors."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- Clamp the value inclusively between lower and upper bounds.\n"
            "- Cover below-lower, in-range, and above-upper behavior.\n"
            "- Objective witnesses: clamp(-5, 0, 10) == 0, "
            "clamp(6, 0, 10) == 6, clamp(14, 0, 10) == 10."
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
            or "below the lower bound"
            in combined
            or "above the upper bound"
            in combined
        ):
            constraints.append(
                "Include literal witnesses below the lower bound, inside the "
                "range, and above the upper bound."
            )

        if (
            "contradicts the current"
            in combined
            and "clamp" in combined
        ):
            constraints.append(
                "Recompute expected values using inclusive lower/upper clamping."
            )

        if (
            "passed every generated pytest test"
            in combined
            or "test suite was non-discriminating"
            in combined
        ):
            constraints.append(
                "At least one ordinary boundary assertion MUST fail against "
                "the deliberately defective implementation."
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
