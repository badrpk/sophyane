"""Ascending unique-sort objective coding contract."""

from __future__ import annotations

from dataclasses import dataclass

from .base import (
    ObjectiveWitness,
    _normalized_request,
    _numeric_list_equality_assertions,
    _render_objective_witness_tests,
)


@dataclass(frozen=True)
class UniqueSortContract:
    """Ascending numeric sorting with duplicate removal."""

    name: str = "unique_sort"
    priority: int = 200

    def matches(
        self,
        request: str,
    ) -> bool:
        request_text = _normalized_request(
            request
        )

        sort_requested = (
            "sort" in request_text
            or "sorted" in request_text
            or "order" in request_text
        )

        unique_requested = (
            "unique" in request_text
            or "remove duplicates" in request_text
            or "remove duplicate" in request_text
            or "without duplicates" in request_text
            or "deduplicate" in request_text
            or "deduplicated" in request_text
        )

        descending_requested = (
            "descending" in request_text
        )

        return (
            sort_requested
            and unique_requested
            and not descending_requested
        )

    def objective_test_source(
        self,
        *,
        module_name: str,
        function_name: str,
    ) -> str:
        return _render_objective_witness_tests(
            module_name=module_name,
            function_name=function_name,
            witnesses=(
                ObjectiveWitness(
                    name="unique_sort_duplicates",
                    arguments=(
                        [3, 1, 3, 2, 1],
                    ),
                    expected=[
                        1,
                        2,
                        3,
                    ],
                ),
                ObjectiveWitness(
                    name="unique_sort_unsorted",
                    arguments=(
                        [9, 2, 5, 2],
                    ),
                    expected=[
                        2,
                        5,
                        9,
                    ],
                ),
            ),
        )

    def validate_test_source(
        self,
        *,
        function_name: str,
        test_source: str,
    ) -> None:
        checked = 0
        discriminates_from_plain_sort = False

        assertions = _numeric_list_equality_assertions(
            function_name=function_name,
            test_source=test_source,
        )

        for values, expected in assertions:

            actual = sorted(
                set(values)
            )

            checked += 1

            plain_sorted = sorted(
                values
            )

            if actual != plain_sorted:
                discriminates_from_plain_sort = True

            if list(expected) != actual:
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "unique-sort request: "
                    f"{function_name}({values!r}) should equal "
                    f"{actual!r}, but the generated test expects "
                    f"{expected!r}."
                )

        if (
            checked > 0
            and not discriminates_from_plain_sort
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT unique-sort "
                "request, but its literal examples are non-discriminating: "
                "they do not expose duplicate removal. Include at least one "
                "ordinary literal input containing duplicates."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect unique-sort implementation may "
            "sort ascending but preserve duplicates.\n"
            "- This isolates the duplicate-removal defect while retaining "
            "otherwise plausible sorting behavior.\n"
            "- Prefer a wrong returned list over crashes or syntax errors."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- Sort numeric values in ascending order and remove duplicates.\n"
            "- Include at least one literal input containing duplicates.\n"
            "- Objective witness: [3, 1, 3, 2, 1] must become [1, 2, 3]."
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
            "non-discriminating" in combined
            or "plain sorting" in combined
        ):
            constraints.append(
                "Use an input containing duplicates so ordinary ascending "
                "sort cannot accidentally satisfy the unique-sort contract."
            )

            constraints.append(
                "Objective witness: [3, 1, 3, 2, 1] must become [1, 2, 3]."
            )

        if (
            "contradicts the current" in combined
            and "unique-sort" in combined
        ):
            constraints.append(
                "Recompute expected output using ascending ordering with "
                "duplicates removed."
            )

        if (
            "passed every generated pytest test" in combined
            or "test suite was non-discriminating" in combined
        ):
            constraints.append(
                "At least one ordinary duplicate-removal assertion MUST fail "
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
