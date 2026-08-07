"""Descending unique-sort objective coding contract."""

from __future__ import annotations

from dataclasses import dataclass

from .base import (
    ObjectiveWitness,
    _normalized_request,
    _numeric_list_equality_assertions,
    _render_objective_witness_tests,
)


@dataclass(frozen=True)
class DescendingUniqueSortContract:
    """Descending numeric sorting with duplicate removal."""

    name: str = "descending_unique_sort"

    # More specific than:
    #   sort                100
    #   descending_sort     200
    #   unique_sort         200
    priority: int = 300

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

        descending_requested = (
            "descending" in request_text
        )

        unique_requested = (
            "unique" in request_text
            or "remove duplicates" in request_text
            or "remove duplicate" in request_text
            or "without duplicates" in request_text
            or "deduplicate" in request_text
            or "deduplicated" in request_text
        )

        return (
            sort_requested
            and descending_requested
            and unique_requested
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
                    name="desc_unique_duplicates",
                    arguments=(
                        [3, 1, 3, 2, 1],
                    ),
                    expected=[
                        3,
                        2,
                        1,
                    ],
                ),
                ObjectiveWitness(
                    name="desc_unique_unsorted",
                    arguments=(
                        [9, 2, 5, 2],
                    ),
                    expected=[
                        9,
                        5,
                        2,
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
        discriminates_from_parent_contracts = False

        assertions = _numeric_list_equality_assertions(
            function_name=function_name,
            test_source=test_source,
        )

        for values, expected in assertions:

            actual = sorted(
                set(values),
                reverse=True,
            )

            checked += 1

            plain_descending = sorted(
                values,
                reverse=True,
            )

            unique_ascending = sorted(
                set(values)
            )

            if (
                actual != plain_descending
                and actual != unique_ascending
            ):
                discriminates_from_parent_contracts = True

            if list(expected) != actual:
                raise ValueError(
                    "Generated pytest contradicts the CURRENT "
                    "descending-unique-sort request: "
                    f"{function_name}({values!r}) should equal "
                    f"{actual!r}, but the generated test expects "
                    f"{expected!r}."
                )

        if (
            checked > 0
            and not discriminates_from_parent_contracts
        ):
            raise ValueError(
                "Generated pytest is correct for the CURRENT "
                "descending-unique-sort request, but its literal examples "
                "do not discriminate the compound contract from its parent "
                "sort contracts. Include an unsorted input containing "
                "duplicates."
            )

    def red_defect_guidance(
        self,
    ) -> str:
        return (
            "PLAUSIBLE DELIBERATE RED DEFECT:\n"
            "- A useful deliberately incorrect descending unique-sort "
            "implementation may sort descending but preserve duplicates.\n"
            "- This keeps descending order correct while deliberately omitting "
            "duplicate removal.\n"
            "- Prefer a wrong returned list over crashes or syntax errors."
        )

    def preflight_constraints(
        self,
    ) -> str:
        return (
            "OBJECTIVE PREFLIGHT CONTRACT CONSTRAINTS:\n"
            "- Sort numeric values in descending order and remove duplicates.\n"
            "- Include an ordinary unsorted literal input containing duplicates.\n"
            "- Objective witness: [3, 1, 3, 2, 1] must become [3, 2, 1]."
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
            or "parent" in combined
        ):
            constraints.extend(
                [
                    (
                        "Use an unsorted input containing duplicates so both "
                        "descending ordering and duplicate removal are observable."
                    ),
                    (
                        "Objective witness: [3, 1, 3, 2, 1] must become "
                        "[3, 2, 1]."
                    ),
                ]
            )

        if (
            "contradicts the current" in combined
            and "descending-unique-sort" in combined
        ):
            constraints.append(
                "Recompute expected output using descending ordering with "
                "duplicates removed."
            )

        if (
            "passed every generated pytest test" in combined
            or "test suite was non-discriminating" in combined
        ):
            constraints.append(
                "At least one ordinary compound-contract assertion MUST fail "
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
