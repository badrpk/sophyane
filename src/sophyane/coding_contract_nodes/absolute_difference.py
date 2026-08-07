"""Absolute-difference objective coding contract."""

from __future__ import annotations

from dataclasses import dataclass

from .base import (
    _literal_equality_assertions,
    _normalized_request,
)


@dataclass(frozen=True)
class AbsoluteDifferenceContract:
    """Absolute numeric difference between two scalar values."""

    name: str = "absolute_difference"
    priority: int = 100

    def matches(
        self,
        request: str,
    ) -> bool:
        request_text = _normalized_request(
            request
        )

        return (
            (
                "absolute difference"
                in request_text
            )
            or (
                "absolute_difference"
                in request_text
            )
            or (
                "absolute difference between"
                in request_text
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
            "def test_objective_absolute_difference_forward():\n"
            f"    assert {function_name}(9, 2) == 7\n"
            "\n"
            "def test_objective_absolute_difference_reverse():\n"
            f"    assert {function_name}(2, 9) == 7\n"
            "\n"
            "def test_objective_absolute_difference_signed():\n"
            f"    assert {function_name}(-3, 4) == 7\n"
        )

    def validate_test_source(
        self,
        *,
        function_name: str,
        test_source: str,
    ) -> None:
        checked = 0
        exposes_signed_subtraction = False

        assertions = _literal_equality_assertions(
            function_name=function_name,
            test_source=test_source,
            argument_count=2,
        )

        for arguments, expected in assertions:
            (
                left,
                right,
            ) = arguments

            items = (
                left,
                right,
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

            actual = abs(
                left
                - right
            )

            checked += 1

            if (
                left - right
                != actual
            ):
                exposes_signed_subtraction = True

            if actual != expected:
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "absolute-difference request: "
                    f"{function_name}({left!r}, {right!r}) "
                    f"should equal {actual!r}, but the generated "
                    f"test expects {expected!r}."
                )

        if (
            checked > 0
            and not exposes_signed_subtraction
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT "
                "absolute-difference request, but its literal examples "
                "are non-discriminating: plain signed subtraction would "
                "produce the same result. Include at least one ordinary "
                "case where the first value is smaller than the second."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect absolute-difference "
            "implementation may return left - right without applying abs().\n"
            "- Use an input where left < right so the signed-subtraction "
            "defect produces a negative value.\n"
            "- Prefer a wrong returned number over crashes or syntax errors."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- Return the non-negative absolute difference between two "
            "numeric values.\n"
            "- Include a witness where the first value is smaller than "
            "the second.\n"
            "- Objective witnesses: absolute_difference(9, 2) == 7 and "
            "absolute_difference(2, 9) == 7."
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
            + str(
                execution_feedback
                or ""
            )
        ).lower()

        constraints: list[str] = []

        if (
            "non-discriminating"
            in combined
            or "signed subtraction"
            in combined
        ):
            constraints.extend(
                [
                    (
                        "Include a literal case where the first numeric "
                        "value is smaller than the second."
                    ),
                    (
                        "Objective witness: absolute_difference(2, 9) "
                        "must equal 7, not -7."
                    ),
                ]
            )

        if (
            "contradicts the current"
            in combined
            and "absolute-difference"
            in combined
        ):
            constraints.append(
                "Recompute expected values using abs(left - right)."
            )

        if (
            "passed every generated pytest test"
            in combined
            or "test suite was non-discriminating"
            in combined
        ):
            constraints.append(
                "At least one ordinary assertion MUST fail against "
                "plain signed subtraction."
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
