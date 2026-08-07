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
        "clamp",
        "median",
        "sort",
        "descending_sort",
        "unique_sort",
        "descending_unique_sort",
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


def test_builtin_contract_loader_returns_deterministic_nodes() -> None:
    from sophyane.coding_contract_nodes import (
        builtin_coding_contracts,
    )

    contracts = builtin_coding_contracts()

    assert tuple(
        contract.name
        for contract in contracts
    ) == (
        "clamp",
        "median",
        "sort",
        "descending_sort",
        "unique_sort",
        "descending_unique_sort",
    )


def test_builtin_contract_loader_returns_fresh_instances() -> None:
    from sophyane.coding_contract_nodes import (
        builtin_coding_contracts,
    )

    first = builtin_coding_contracts()
    second = builtin_coding_contracts()

    assert first is not second
    assert first[0] is not second[0]
    assert first[1] is not second[1]


def test_facade_load_builtin_api_exists() -> None:
    from sophyane.coding_contracts import (
        load_builtin_coding_contracts,
    )

    assert callable(
        load_builtin_coding_contracts
    )


def test_isolated_contract_registry_starts_empty() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
    )

    registry = CodingContractRegistry()

    assert registry.snapshot() == ()


def test_isolated_registry_registration_does_not_mutate_default() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
        MedianContract,
        registered_coding_contracts,
    )

    before = tuple(
        contract.name
        for contract in registered_coding_contracts()
    )

    registry = CodingContractRegistry()

    registry.register(
        MedianContract()
    )

    assert tuple(
        contract.name
        for contract in registry.snapshot()
    ) == (
        "median",
    )

    after = tuple(
        contract.name
        for contract in registered_coding_contracts()
    )

    assert after == before


def test_isolated_registry_rejects_duplicate_name() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
        MedianContract,
    )

    registry = CodingContractRegistry()

    registry.register(
        MedianContract()
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        registry.register(
            MedianContract()
        )


def test_isolated_registry_matches_in_registration_order() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
        MedianContract,
        SortContract,
    )

    registry = CodingContractRegistry()

    registry.register(
        MedianContract()
    )
    registry.register(
        SortContract()
    )

    assert (
        registry.match(
            "Calculate the median of numeric values."
        ).name
        == "median"
    )

    assert (
        registry.match(
            "Sort numeric values in ascending order."
        ).name
        == "sort"
    )


def test_isolated_registry_nonmatch_returns_none() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
    )

    registry = CodingContractRegistry()

    assert (
        registry.match(
            "Create add(a, b)."
        )
        is None
    )


def test_builtin_loader_can_populate_isolated_registry() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
        load_builtin_coding_contracts,
    )

    registry = CodingContractRegistry()

    returned = load_builtin_coding_contracts(
        registry
    )

    assert returned is registry

    assert tuple(
        contract.name
        for contract in registry.snapshot()
    ) == (
        "clamp",
        "median",
        "sort",
        "descending_sort",
        "unique_sort",
        "descending_unique_sort",
    )


def test_builtin_loader_isolated_registry_does_not_mutate_default() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
        load_builtin_coding_contracts,
        registered_coding_contracts,
    )

    before = tuple(
        contract.name
        for contract in registered_coding_contracts()
    )

    registry = CodingContractRegistry()

    load_builtin_coding_contracts(
        registry
    )

    after = tuple(
        contract.name
        for contract in registered_coding_contracts()
    )

    assert after == before


def test_builtin_loader_rejects_duplicate_loading_into_same_registry() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
        load_builtin_coding_contracts,
    )

    registry = CodingContractRegistry()

    load_builtin_coding_contracts(
        registry
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        load_builtin_coding_contracts(
            registry
        )


def test_builtin_contracts_define_priority() -> None:
    from sophyane.coding_contracts import (
        registered_coding_contracts,
    )

    for contract in registered_coding_contracts():
        assert isinstance(
            contract.priority,
            int,
        )


def test_higher_priority_contract_wins_over_registration_order() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
    )

    class LowPriority:
        name = "low"
        priority = 10

        def matches(self, request):
            return True

        def objective_test_source(self, **kwargs):
            return None

        def validate_test_source(self, **kwargs):
            return None

        def preflight_constraints(self):
            return ""

        def corrective_constraints(self, **kwargs):
            return ""

    class HighPriority:
        name = "high"
        priority = 100

        def matches(self, request):
            return True

        def objective_test_source(self, **kwargs):
            return None

        def validate_test_source(self, **kwargs):
            return None

        def preflight_constraints(self):
            return ""

        def corrective_constraints(self, **kwargs):
            return ""

    registry = CodingContractRegistry()

    registry.register(
        LowPriority()
    )
    registry.register(
        HighPriority()
    )

    matched = registry.match(
        "ambiguous request"
    )

    assert matched is not None
    assert matched.name == "high"


def test_equal_priority_uses_registration_order() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
    )

    class First:
        name = "first"
        priority = 50

        def matches(self, request):
            return True

        def objective_test_source(self, **kwargs):
            return None

        def validate_test_source(self, **kwargs):
            return None

        def preflight_constraints(self):
            return ""

        def corrective_constraints(self, **kwargs):
            return ""

    class Second:
        name = "second"
        priority = 50

        def matches(self, request):
            return True

        def objective_test_source(self, **kwargs):
            return None

        def validate_test_source(self, **kwargs):
            return None

        def preflight_constraints(self):
            return ""

        def corrective_constraints(self, **kwargs):
            return ""

    registry = CodingContractRegistry()

    registry.register(
        First()
    )
    registry.register(
        Second()
    )

    matched = registry.match(
        "ambiguous request"
    )

    assert matched is not None
    assert matched.name == "first"


def test_missing_priority_defaults_to_zero() -> None:
    from sophyane.coding_contracts import (
        CodingContractRegistry,
    )

    class LegacyContract:
        name = "legacy"

        def matches(self, request):
            return True

        def objective_test_source(self, **kwargs):
            return None

        def validate_test_source(self, **kwargs):
            return None

        def preflight_constraints(self):
            return ""

        def corrective_constraints(self, **kwargs):
            return ""

    registry = CodingContractRegistry()

    registry.register(
        LegacyContract()
    )

    matched = registry.match(
        "legacy request"
    )

    assert matched is not None
    assert matched.name == "legacy"


DESCENDING_SORT_REQUEST = (
    "Create reverse_order.py with descending_values(values). "
    "Sort the numeric list in descending order."
)


def test_descending_sort_contract_matches() -> None:
    contract = match_coding_contract(
        DESCENDING_SORT_REQUEST
    )

    assert contract is not None
    assert contract.name == "descending_sort"
    assert contract.priority == 200


def test_descending_sort_overrides_generic_sort_contract() -> None:
    from sophyane.coding_contracts import (
        registered_coding_contracts,
    )

    matches = [
        contract
        for contract in registered_coding_contracts()
        if contract.matches(
            DESCENDING_SORT_REQUEST
        )
    ]

    names = [
        contract.name
        for contract in matches
    ]

    assert "sort" in names
    assert "descending_sort" in names

    selected = match_coding_contract(
        DESCENDING_SORT_REQUEST
    )

    assert selected is not None
    assert selected.name == "descending_sort"


def test_descending_contract_supplies_objective_tests() -> None:
    source = objective_preflight_test_source(
        request=DESCENDING_SORT_REQUEST,
        module_name="reverse_order",
        function_name="descending_values",
    )

    assert source is not None

    assert (
        "descending_values([1, 9, 2, 5]) == [9, 5, 2, 1]"
        in source
    )

    assert (
        "descending_values([3, 1, 3, 2]) == [3, 3, 2, 1]"
        in source
    )


def test_wrong_descending_contract_is_rejected() -> None:
    source = """
from reverse_order import descending_values

def test_wrong():
    assert descending_values([1, 9, 2, 5]) == [1, 2, 5, 9]
"""

    with pytest.raises(
        ValueError,
        match="descending-sort request",
    ):
        validate_generated_test_contract(
            request=DESCENDING_SORT_REQUEST,
            function_name="descending_values",
            test_source=source,
        )


def test_descending_preflight_contains_objective_witness() -> None:
    guidance = format_red_preflight_constraints(
        request=DESCENDING_SORT_REQUEST
    )

    assert "[1, 9, 2, 5]" in guidance
    assert "[9, 5, 2, 1]" in guidance


def test_descending_sort_exposes_plausible_red_defect_guidance() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    guidance = format_red_defect_guidance(
        request=DESCENDING_SORT_REQUEST
    )

    assert "ascending" in guidance.lower()
    assert "deliberately incorrect" in guidance.lower()


def test_median_exposes_mean_as_plausible_red_defect() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    guidance = format_red_defect_guidance(
        request=MEDIAN_REQUEST
    )

    assert "arithmetic mean" in guidance.lower()


def test_sort_exposes_behavioral_red_defect_guidance() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    guidance = format_red_defect_guidance(
        request=SORT_REQUEST
    )

    assert (
        "unchanged" in guidance.lower()
        or "descending" in guidance.lower()
    )


def test_nonmatching_request_has_no_red_defect_guidance() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    assert (
        format_red_defect_guidance(
            request="Create add.py with add(a, b)."
        )
        == ""
    )


UNIQUE_SORT_REQUEST = (
    "Create unique_order.py with unique_values(values). "
    "Sort numeric values in ascending order and remove duplicates."
)


def test_unique_sort_contract_matches() -> None:
    contract = match_coding_contract(
        UNIQUE_SORT_REQUEST
    )

    assert contract is not None
    assert contract.name == "unique_sort"
    assert contract.priority == 200


def test_unique_sort_overrides_generic_sort() -> None:
    from sophyane.coding_contracts import (
        registered_coding_contracts,
    )

    matches = [
        contract
        for contract in registered_coding_contracts()
        if contract.matches(
            UNIQUE_SORT_REQUEST
        )
    ]

    names = {
        contract.name
        for contract in matches
    }

    assert "sort" in names
    assert "unique_sort" in names

    selected = match_coding_contract(
        UNIQUE_SORT_REQUEST
    )

    assert selected is not None
    assert selected.name == "unique_sort"


def test_unique_sort_objective_tests() -> None:
    source = objective_preflight_test_source(
        request=UNIQUE_SORT_REQUEST,
        module_name="unique_order",
        function_name="unique_values",
    )

    assert source is not None

    assert (
        "unique_values([3, 1, 3, 2, 1]) == [1, 2, 3]"
        in source
    )


def test_wrong_unique_sort_contract_rejected() -> None:
    source = """
from unique_order import unique_values

def test_wrong():
    assert unique_values([3, 1, 3, 2, 1]) == [1, 1, 2, 3, 3]
"""

    with pytest.raises(
        ValueError,
        match="unique-sort request",
    ):
        validate_generated_test_contract(
            request=UNIQUE_SORT_REQUEST,
            function_name="unique_values",
            test_source=source,
        )


def test_unique_sort_requires_duplicate_witness() -> None:
    source = """
from unique_order import unique_values

def test_weak():
    assert unique_values([3, 1, 2]) == [1, 2, 3]
"""

    with pytest.raises(
        ValueError,
        match="non-discriminating",
    ):
        validate_generated_test_contract(
            request=UNIQUE_SORT_REQUEST,
            function_name="unique_values",
            test_source=source,
        )


def test_unique_sort_red_guidance_targets_missing_deduplication() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    guidance = format_red_defect_guidance(
        request=UNIQUE_SORT_REQUEST
    ).lower()

    assert "preserve duplicates" in guidance
    assert "deliberately incorrect" in guidance


DESCENDING_UNIQUE_SORT_REQUEST = (
    "Create compound_order.py with descending_unique_values(values). "
    "Sort numeric values in descending order and remove duplicates."
)


def test_descending_unique_sort_contract_matches() -> None:
    contract = match_coding_contract(
        DESCENDING_UNIQUE_SORT_REQUEST
    )

    assert contract is not None
    assert contract.name == "descending_unique_sort"
    assert contract.priority == 300


def test_descending_unique_sort_has_real_parent_overlap() -> None:
    from sophyane.coding_contracts import (
        registered_coding_contracts,
    )

    matches = [
        contract
        for contract in registered_coding_contracts()
        if contract.matches(
            DESCENDING_UNIQUE_SORT_REQUEST
        )
    ]

    names = {
        contract.name
        for contract in matches
    }

    assert "sort" in names
    assert "descending_sort" in names
    assert "descending_unique_sort" in names

    selected = match_coding_contract(
        DESCENDING_UNIQUE_SORT_REQUEST
    )

    assert selected is not None
    assert selected.name == "descending_unique_sort"
    assert selected.priority == 300


def test_descending_unique_sort_objective_tests() -> None:
    source = objective_preflight_test_source(
        request=DESCENDING_UNIQUE_SORT_REQUEST,
        module_name="compound_order",
        function_name="descending_unique_values",
    )

    assert source is not None

    assert (
        "descending_unique_values([3, 1, 3, 2, 1]) == [3, 2, 1]"
        in source
    )

    assert (
        "descending_unique_values([9, 2, 5, 2]) == [9, 5, 2]"
        in source
    )


def test_wrong_descending_unique_sort_contract_rejected() -> None:
    source = """
from compound_order import descending_unique_values

def test_wrong():
    assert descending_unique_values([3, 1, 3, 2, 1]) == [3, 3, 2, 1, 1]
"""

    with pytest.raises(
        ValueError,
        match="descending-unique-sort request",
    ):
        validate_generated_test_contract(
            request=DESCENDING_UNIQUE_SORT_REQUEST,
            function_name="descending_unique_values",
            test_source=source,
        )


def test_descending_unique_sort_guidance_targets_deduplication() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    guidance = format_red_defect_guidance(
        request=DESCENDING_UNIQUE_SORT_REQUEST
    ).lower()

    assert "descending" in guidance
    assert "preserve duplicates" in guidance


def test_descending_unique_sort_preflight_has_compound_witness() -> None:
    guidance = format_red_preflight_constraints(
        request=DESCENDING_UNIQUE_SORT_REQUEST
    )

    assert "[3, 1, 3, 2, 1]" in guidance
    assert "[3, 2, 1]" in guidance


CLAMP_REQUEST = (
    "Create bounds.py with clamp_value(value, lower, upper). "
    "Clamp the numeric value between a minimum lower bound "
    "and maximum upper bound."
)


def test_clamp_contract_matches() -> None:
    contract = match_coding_contract(
        CLAMP_REQUEST
    )

    assert contract is not None
    assert contract.name == "clamp"
    assert contract.priority == 100


def test_clamp_objective_tests_cover_three_regions() -> None:
    source = objective_preflight_test_source(
        request=CLAMP_REQUEST,
        module_name="bounds",
        function_name="clamp_value",
    )

    assert source is not None

    assert "clamp_value(-5, 0, 10) == 0" in source
    assert "clamp_value(6, 0, 10) == 6" in source
    assert "clamp_value(14, 0, 10) == 10" in source


def test_clamp_objective_tests_validate() -> None:
    source = objective_preflight_test_source(
        request=CLAMP_REQUEST,
        module_name="bounds",
        function_name="clamp_value",
    )

    assert source is not None

    validate_generated_test_contract(
        request=CLAMP_REQUEST,
        function_name="clamp_value",
        test_source=source,
    )


def test_wrong_clamp_expected_value_is_rejected() -> None:
    source = """
from bounds import clamp_value

def test_wrong():
    assert clamp_value(-5, 0, 10) == -5
"""

    with pytest.raises(
        ValueError,
        match="clamp request",
    ):
        validate_generated_test_contract(
            request=CLAMP_REQUEST,
            function_name="clamp_value",
            test_source=source,
        )


def test_clamp_requires_all_three_behavioral_regions() -> None:
    source = """
from bounds import clamp_value

def test_inside():
    assert clamp_value(5, 0, 10) == 5
"""

    with pytest.raises(
        ValueError,
        match="non-discriminating",
    ):
        validate_generated_test_contract(
            request=CLAMP_REQUEST,
            function_name="clamp_value",
            test_source=source,
        )


def test_clamp_red_guidance_targets_missing_lower_bound() -> None:
    from sophyane.coding_contracts import (
        format_red_defect_guidance,
    )

    guidance = format_red_defect_guidance(
        request=CLAMP_REQUEST
    ).lower()

    assert "upper bound" in guidance
    assert "lower bound" in guidance
    assert "deliberately incorrect" in guidance


def test_literal_equality_assertion_extractor_direct_call() -> None:
    from sophyane.coding_contract_nodes.base import (
        _literal_equality_assertions,
    )

    assertions = _literal_equality_assertions(
        function_name="clamp_value",
        test_source="""
from bounds import clamp_value

def test_one():
    assert clamp_value(-5, 0, 10) == 0
""",
        argument_count=3,
    )

    assert assertions == (
        (
            (
                -5,
                0,
                10,
            ),
            0,
        ),
    )


def test_literal_equality_assertion_extractor_module_call() -> None:
    from sophyane.coding_contract_nodes.base import (
        _literal_equality_assertions,
    )

    assertions = _literal_equality_assertions(
        function_name="clamp_value",
        test_source="""
import bounds

def test_one():
    assert bounds.clamp_value(14, 0, 10) == 10
""",
        argument_count=3,
    )

    assert assertions == (
        (
            (
                14,
                0,
                10,
            ),
            10,
        ),
    )


def test_literal_equality_assertion_extractor_ignores_dynamic_values() -> None:
    from sophyane.coding_contract_nodes.base import (
        _literal_equality_assertions,
    )

    assertions = _literal_equality_assertions(
        function_name="clamp_value",
        test_source="""
from bounds import clamp_value

def test_dynamic(value, lower, upper, expected):
    assert clamp_value(value, lower, upper) == expected
""",
        argument_count=3,
    )

    assert assertions == ()


def test_literal_equality_assertion_extractor_accepts_reversed_equality() -> None:
    from sophyane.coding_contract_nodes.base import (
        _literal_equality_assertions,
    )

    assertions = _literal_equality_assertions(
        function_name="clamp_value",
        test_source="""
from bounds import clamp_value

def test_reverse():
    assert 0 == clamp_value(-5, 0, 10)
""",
        argument_count=3,
    )

    assert assertions == (
        (
            (
                -5,
                0,
                10,
            ),
            0,
        ),
    )
