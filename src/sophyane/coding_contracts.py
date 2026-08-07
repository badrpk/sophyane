"""Objective coding-contract nodes for Sophyane adaptive TDD.

Contract nodes contain semantics that the harness can establish independently
of the coding model. They may recognize a request, provide objective tests,
validate generated tests, and expose compact retry guidance.

They do NOT execute code and do NOT decide success. Pytest remains authoritative.
"""

from __future__ import annotations

import ast
import statistics
from dataclasses import dataclass
from typing import Protocol


class CodingContract(Protocol):
    """Interface implemented by deterministic coding-contract nodes."""

    name: str

    def matches(self, request: str) -> bool:
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

    def preflight_constraints(self) -> str:
        ...

    def corrective_constraints(
        self,
        *,
        last_error: str = "",
        execution_feedback: str = "",
    ) -> str:
        ...


def _normalized_request(request: str) -> str:
    return " ".join(
        str(request or "")
        .casefold()
        .split()
    )


def _called_function_name(
    call: ast.Call,
) -> str | None:
    """Return the terminal function name for direct or module-qualified calls."""
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


@dataclass(frozen=True)
class SortContract:
    """Deterministic contract for ascending numeric-list sorting."""

    name: str = "sort"

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
                ) != 1
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


@dataclass(frozen=True)
class MedianContract:
    """Deterministic contract for explicitly requested numeric median behavior."""

    name: str = "median"

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
        """Validate literal median assertions against Python's reference median."""
        try:
            tree = ast.parse(
                str(test_source or "")
            )

        except SyntaxError as error:
            raise ValueError(
                "Generated test contract is syntactically invalid"
            ) from error

        checked = 0
        discriminates_from_mean = False

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
            right = (
                comparison
                .comparators[0]
            )

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
                ) != 1
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
                # Dynamic/non-literal assertions remain subject to runtime truth.
                continue

            if not isinstance(
                values,
                (list, tuple),
            ):
                continue

            if not values:
                # Empty-input semantics are not implied merely by "median".
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


_CONTRACTS: list[CodingContract] = []


def register_coding_contract(
    contract: CodingContract,
) -> None:
    """Register one deterministic coding contract exactly once by name."""
    name = str(
        getattr(
            contract,
            "name",
            "",
        )
        or ""
    ).strip()

    if not name:
        raise ValueError(
            "Coding contract must define a non-empty name"
        )

    if any(
        existing.name == name
        for existing in _CONTRACTS
    ):
        raise ValueError(
            f"Coding contract {name!r} is already registered"
        )

    _CONTRACTS.append(
        contract
    )


def registered_coding_contracts(
) -> tuple[CodingContract, ...]:
    """Return an immutable snapshot of the registered contract nodes."""
    return tuple(
        _CONTRACTS
    )


register_coding_contract(
    MedianContract()
)

register_coding_contract(
    SortContract()
)


def match_coding_contract(
    request: str,
) -> CodingContract | None:
    """Return the first deterministic contract node matching CURRENT request."""
    for contract in registered_coding_contracts():
        if contract.matches(
            request
        ):
            return contract

    return None


def validate_generated_test_contract(
    *,
    request: str,
    function_name: str,
    test_source: str,
) -> None:
    contract = match_coding_contract(
        request
    )

    if contract is None:
        return

    contract.validate_test_source(
        function_name=function_name,
        test_source=test_source,
    )


def objective_preflight_test_source(
    *,
    request: str,
    module_name: str,
    function_name: str,
) -> str | None:
    contract = match_coding_contract(
        request
    )

    if contract is None:
        return None

    return contract.objective_test_source(
        module_name=module_name,
        function_name=function_name,
    )


def format_red_preflight_constraints(
    *,
    request: str,
) -> str:
    contract = match_coding_contract(
        request
    )

    if contract is None:
        return ""

    return contract.preflight_constraints()


def format_red_corrective_constraints(
    *,
    request: str,
    last_error: str = "",
    execution_feedback: str = "",
) -> str:
    contract = match_coding_contract(
        request
    )

    if contract is None:
        return ""

    return contract.corrective_constraints(
        last_error=last_error,
        execution_feedback=execution_feedback,
    )
