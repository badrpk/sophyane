"""Ascending-sort objective coding contract."""

from __future__ import annotations

from dataclasses import dataclass

from .base import (
    _literal_equality_assertions,
    _normalized_request,
)


@dataclass(frozen=True)
class SortContract:
    """Deterministic contract for ascending numeric-list sorting."""

    name: str = "sort"
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
                "sort" in request_text
                or "sorted" in request_text
            )
            and (
                "ascending" in request_text
                or "in ascending order" in request_text
                or "sort" in request_text
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
            "def test_objective_sort_unsorted():\n"
            f"    assert {function_name}([9, 1, 5, 2]) == [1, 2, 5, 9]\n"
            "\n"
            "def test_objective_sort_duplicates():\n"
            f"    assert {function_name}([3, 1, 3, 2]) == [1, 2, 3, 3]\n"
        )

    def validate_test_source(
        self,
        *,
        function_name: str,
        test_source: str,
    ) -> None:
        checked = 0
        discriminates_from_identity = False

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
                values
            )

            checked += 1

            if list(values) != actual:
                discriminates_from_identity = True

            if list(expected) != actual:
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "ascending-sort request: "
                    f"{function_name}({values!r}) should equal "
                    f"{actual!r}, but the generated test expects "
                    f"{expected!r}."
                )

        if (
            checked > 0
            and not discriminates_from_identity
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT sort request, "
                "but its literal examples are non-discriminating: the input "
                "is already sorted. Include at least one ordinary unsorted "
                "literal input."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect ascending-sort implementation may "
            "return the input unchanged or sort in descending order.\n"
            "- Prefer a behaviorally wrong returned list over crashes."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- This task requires ascending-order sorting.\n"
            "- Include at least one ordinary unsorted literal input.\n"
            "- Objective witness: [9, 1, 5, 2] must become [1, 2, 5, 9].\n"
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
            or "already sorted"
            in combined
        ):
            constraints.extend(
                [
                    (
                        "Use an ordinary unsorted literal input so an "
                        "identity implementation cannot accidentally pass."
                    ),
                    (
                        "Objective witness: [9, 1, 5, 2] must become "
                        "[1, 2, 5, 9]."
                    ),
                ]
            )

        if (
            "contradicts the current"
            in combined
            and "sort"
            in combined
        ):
            constraints.append(
                "Recompute expected output using ascending ordering from "
                "the CURRENT request."
            )

        if (
            "passed every generated pytest test"
            in combined
            or "test suite was non-discriminating"
            in combined
        ):
            constraints.append(
                "At least one ordinary sorting assertion MUST fail against "
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
