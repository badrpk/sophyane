"""Regression tests for deterministic adaptive-TDD coding contracts."""

from __future__ import annotations

import pytest

from sophyane.coding_contracts import (
    format_red_corrective_constraints,
    format_red_preflight_constraints,
    match_coding_contract,
    objective_preflight_test_source,
    validate_generated_test_contract,
)


MEDIAN_REQUEST = (
    "Create stats.py with median_value(values). "
    "Calculate the median for odd and even numeric lists."
)


def test_median_contract_matches_explicit_request() -> None:
    contract = match_coding_contract(
        MEDIAN_REQUEST
    )

    assert contract is not None
    assert contract.name == "median"


def test_unrelated_request_has_no_contract() -> None:
    assert (
        match_coding_contract(
            "Create math_ops.py with add(a, b)."
        )
        is None
    )


def test_median_contract_supplies_objective_tests() -> None:
    source = objective_preflight_test_source(
        request=MEDIAN_REQUEST,
        module_name="stats",
        function_name="median_value",
    )

    assert source is not None
    assert "median_value([1, 2, 100]) == 2" in source
    assert "median_value([1, 4, 9, 100]) == 6.5" in source


def test_objective_median_tests_validate() -> None:
    source = objective_preflight_test_source(
        request=MEDIAN_REQUEST,
        module_name="stats",
        function_name="median_value",
    )

    assert source is not None

    validate_generated_test_contract(
        request=MEDIAN_REQUEST,
        function_name="median_value",
        test_source=source,
    )


def test_wrong_median_expected_value_is_rejected() -> None:
    source = """
from stats import median_value

def test_wrong():
    assert median_value([1, 2, 100]) == 37
"""

    with pytest.raises(
        ValueError,
        match="contradicts the CURRENT median request",
    ):
        validate_generated_test_contract(
            request=MEDIAN_REQUEST,
            function_name="median_value",
            test_source=source,
        )


def test_non_discriminating_median_contract_is_rejected() -> None:
    source = """
from stats import median_value

def test_non_discriminating():
    assert median_value([1, 2, 3]) == 2
"""

    with pytest.raises(
        ValueError,
        match="non-discriminating",
    ):
        validate_generated_test_contract(
            request=MEDIAN_REQUEST,
            function_name="median_value",
            test_source=source,
        )


def test_module_qualified_median_call_is_validated() -> None:
    source = """
import stats

def test_wrong():
    assert stats.median_value([1, 2, 100]) == 50
"""

    with pytest.raises(
        ValueError,
        match="contradicts the CURRENT median request",
    ):
        validate_generated_test_contract(
            request=MEDIAN_REQUEST,
            function_name="median_value",
            test_source=source,
        )


def test_dynamic_assertion_is_not_given_invented_semantics() -> None:
    source = """
from stats import median_value

def test_dynamic(values, expected):
    assert median_value(values) == expected
"""

    validate_generated_test_contract(
        request=MEDIAN_REQUEST,
        function_name="median_value",
        test_source=source,
    )


def test_non_matching_request_is_untouched() -> None:
    validate_generated_test_contract(
        request="Create math_ops.py with add(a, b).",
        function_name="add",
        test_source="""
from math_ops import add

def test_anything():
    assert add(1, 2) == 999
""",
    )

    assert (
        objective_preflight_test_source(
            request="Create math_ops.py with add(a, b).",
            module_name="math_ops",
            function_name="add",
        )
        is None
    )

    assert (
        format_red_preflight_constraints(
            request="Create math_ops.py with add(a, b)."
        )
        == ""
    )


def test_median_preflight_guidance_contains_objective_witness() -> None:
    guidance = format_red_preflight_constraints(
        request=MEDIAN_REQUEST
    )

    assert "[1, 2, 100]" in guidance
    assert "median 2" in guidance


def test_median_corrective_guidance_uses_validator_evidence() -> None:
    guidance = format_red_corrective_constraints(
        request=MEDIAN_REQUEST,
        last_error=(
            "Generated pytest is correct for the CURRENT median request, "
            "but its literal examples are non-discriminating: "
            "arithmetic mean and median produce the same expected values."
        ),
    )

    assert "[1, 2, 100]" in guidance
    assert "median" in guidance.lower()


def test_corrective_guidance_is_empty_without_relevant_evidence() -> None:
    assert (
        format_red_corrective_constraints(
            request=MEDIAN_REQUEST,
        )
        == ""
    )

SORT_REQUEST = (
    "Create ordering.py with ascending_values(values). "
    "Sort the numeric list in ascending order."
)


def test_sort_contract_matches_explicit_request() -> None:
    contract = match_coding_contract(
        SORT_REQUEST
    )

    assert contract is not None
    assert contract.name == "sort"


def test_sort_contract_supplies_objective_tests() -> None:
    source = objective_preflight_test_source(
        request=SORT_REQUEST,
        module_name="ordering",
        function_name="ascending_values",
    )

    assert source is not None

    assert (
        "ascending_values([9, 1, 5, 2]) == [1, 2, 5, 9]"
        in source
    )

    assert (
        "ascending_values([3, 1, 3, 2]) == [1, 2, 3, 3]"
        in source
    )


def test_objective_sort_tests_validate() -> None:
    source = objective_preflight_test_source(
        request=SORT_REQUEST,
        module_name="ordering",
        function_name="ascending_values",
    )

    assert source is not None

    validate_generated_test_contract(
        request=SORT_REQUEST,
        function_name="ascending_values",
        test_source=source,
    )


def test_wrong_sort_contract_is_rejected() -> None:
    source = """
from ordering import ascending_values

def test_wrong():
    assert ascending_values([9, 1, 5, 2]) == [9, 5, 2, 1]
"""

    with pytest.raises(
        ValueError,
        match="ascending-sort request",
    ):
        validate_generated_test_contract(
            request=SORT_REQUEST,
            function_name="ascending_values",
            test_source=source,
        )


def test_already_sorted_only_contract_is_rejected() -> None:
    source = """
from ordering import ascending_values

def test_weak():
    assert ascending_values([1, 2, 3, 4]) == [1, 2, 3, 4]
"""

    with pytest.raises(
        ValueError,
        match="non-discriminating",
    ):
        validate_generated_test_contract(
            request=SORT_REQUEST,
            function_name="ascending_values",
            test_source=source,
        )


def test_module_qualified_sort_call_is_validated() -> None:
    source = """
import ordering

def test_wrong():
    assert ordering.ascending_values([4, 1, 3]) == [4, 3, 1]
"""

    with pytest.raises(
        ValueError,
        match="ascending-sort request",
    ):
        validate_generated_test_contract(
            request=SORT_REQUEST,
            function_name="ascending_values",
            test_source=source,
        )


def test_sort_dynamic_assertion_is_not_given_invented_semantics() -> None:
    source = """
from ordering import ascending_values

def test_dynamic(values, expected):
    assert ascending_values(values) == expected
"""

    validate_generated_test_contract(
        request=SORT_REQUEST,
        function_name="ascending_values",
        test_source=source,
    )


def test_sort_preflight_contains_unsorted_witness() -> None:
    guidance = format_red_preflight_constraints(
        request=SORT_REQUEST
    )

    assert "[9, 1, 5, 2]" in guidance
    assert "[1, 2, 5, 9]" in guidance


def test_sort_corrective_guidance_uses_validator_evidence() -> None:
    guidance = format_red_corrective_constraints(
        request=SORT_REQUEST,
        last_error=(
            "Generated pytest is correct for the CURRENT sort request, "
            "but its literal examples are non-discriminating: "
            "the input is already sorted."
        ),
    )

    assert "[9, 1, 5, 2]" in guidance
    assert "[1, 2, 5, 9]" in guidance


def test_sort_corrective_guidance_empty_without_evidence() -> None:
    assert (
        format_red_corrective_constraints(
            request=SORT_REQUEST,
        )
        == ""
    )



def test_registered_contract_snapshot_contains_builtin_nodes() -> None:
    from sophyane.coding_contracts import (
        registered_coding_contracts,
    )

    contracts = registered_coding_contracts()

    assert tuple(
        contract.name
        for contract in contracts
    ) == (
        "median",
        "sort",
    )


def test_registered_contract_snapshot_is_immutable_tuple() -> None:
    from sophyane.coding_contracts import (
        registered_coding_contracts,
    )

    assert isinstance(
        registered_coding_contracts(),
        tuple,
    )


def test_duplicate_contract_name_is_rejected() -> None:
    from sophyane.coding_contracts import (
        MedianContract,
        register_coding_contract,
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        register_coding_contract(
            MedianContract()
        )


def test_contract_without_name_is_rejected() -> None:
    from sophyane.coding_contracts import (
        register_coding_contract,
    )

    class NamelessContract:
        name = ""

    with pytest.raises(
        ValueError,
        match="non-empty name",
    ):
        register_coding_contract(
            NamelessContract()
        )
