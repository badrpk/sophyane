"""Median objective coding contract."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .base import (
    _literal_equality_assertions,
    _normalized_request,
)


@dataclass(frozen=True)
class MedianContract:
    """Deterministic contract for explicitly requested numeric median behavior."""

    name: str = "median"
    priority: int = 100

    def matches(
        self,
        request: str,
    ) -> bool:
        return (
            "median"
            in _normalized_request(
                request
            )
        )

    def objective_test_source(
        self,
        *,
        module_name: str,
        function_name: str,
    ) -> str:
        # Both examples are ordinary behavioral witnesses and distinguish
        # median from the plausible arithmetic-mean defect.
        return (
            f"from {module_name} import {function_name}\n"
            "\n"
            "def test_objective_median_odd():\n"
            f"    assert {function_name}([1, 2, 100]) == 2\n"
            "\n"
            "def test_objective_median_even():\n"
            f"    assert {function_name}([1, 4, 9, 100]) == 6.5\n"
        )

    def validate_test_source(
        self,
        *,
        function_name: str,
        test_source: str,
    ) -> None:
        checked = 0
        discriminates_from_mean = False

        assertions = _literal_equality_assertions(
            function_name=function_name,
            test_source=test_source,
            argument_count=1,
        )

        for arguments, expected in assertions:
            (
                values,
            ) = arguments

            if not isinstance(
                values,
                (list, tuple),
            ):
                continue

            if not values:
                # Empty-input behavior is not implied merely by "median".
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

            if (
                not isinstance(
                    expected,
                    (int, float),
                )
                or isinstance(
                    expected,
                    bool,
                )
            ):
                continue

            actual = statistics.median(
                values
            )

            checked += 1

            arithmetic_mean = (
                sum(values)
                / len(values)
            )

            if (
                float(actual)
                != float(
                    arithmetic_mean
                )
            ):
                discriminates_from_mean = True

            if (
                float(actual)
                != float(
                    expected
                )
            ):
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "median request: "
                    f"{function_name}({values!r}) should equal "
                    f"{actual!r}, but the generated test expects "
                    f"{expected!r}. Regenerate the test contract "
                    "from the user request before RED execution."
                )

        if (
            checked > 0
            and not discriminates_from_mean
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT median request, "
                "but its literal examples are non-discriminating: arithmetic "
                "mean and median produce the same expected values. Include at "
                "least one ordinary literal input where mean != median, such as "
                "[1, 2, 100] or another asymmetric/unsorted case."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect median implementation may compute "
            "the arithmetic mean instead of the median.\n"
            "- Do not make the defect syntactic or crash-only.\n"
            "- The objective tests must expose the wrong returned value."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- For this median task, tests must include at least one ordinary "
            "literal numeric example where arithmetic mean and median differ.\n"
            "- Objective witness available before generation: "
            "[1, 2, 100] has median 2.\n"
            "- If [1, 2, 100] is used, its expected value MUST be 2; "
            "do not substitute the arithmetic mean."
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
            or "mean and median"
            in combined
            or "arithmetic mean"
            in combined
        ):
            constraints.extend(
                [
                    (
                        "For this median task, include at least one ordinary "
                        "literal numeric example where arithmetic mean and "
                        "median differ."
                    ),
                    (
                        "Known objective witness: [1, 2, 100] has median 2 "
                        "while its arithmetic mean is not 2."
                    ),
                    (
                        "If that witness is used, its expected median MUST be 2."
                    ),
                ]
            )

        if (
            "contradicts the current median request"
            in combined
        ):
            constraints.extend(
                [
                    (
                        "Recompute every expected median value from the CURRENT "
                        "request; do not preserve an expected value that the "
                        "validator already rejected."
                    ),
                    (
                        "Known objective contract example: "
                        "median([1, 2, 100]) is 2."
                    ),
                ]
            )

        if (
            "repeated a red source/test pair"
            in combined
            or "materially different"
            in combined
        ):
            constraints.append(
                "Do not repeat an observationally equivalent rejected "
                "broken_source/test_source pair; change the behavioral defect "
                "and/or the discriminating ordinary inputs."
            )

        if (
            "passed every generated pytest test"
            in combined
            or "test suite was non-discriminating"
            in combined
        ):
            constraints.append(
                "At least one ordinary behavioral assertion MUST fail against "
                "the deliberately defective implementation while remaining "
                "correct for the requested behavior."
            )

        unique: list[str] = []

        for constraint in constraints:
            if constraint not in unique:
                unique.append(
                    constraint
                )

        if not unique:
            return ""

        return (
            "OBJECTIVE CORRECTIVE CONSTRAINTS FOR THIS RETRY:\n"
            + "\n".join(
                f"- {constraint}"
                for constraint in unique
            )
        )
