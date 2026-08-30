import inspect

from sophyane.local_coding_capability import (
    _explicit_record_function_contract,
    _python_adaptive_tdd_action,
)


def test_explicit_record_contract_is_generic():
    spec = _explicit_record_function_contract(
        filename="records_tool.py",
        request=(
            "Define function choose_best(items). "
            "items is a list of dictionaries containing id and score. "
            "Ignore records missing id or score. "
            "If an id appears multiple times, keep the record "
            "with the highest numeric score. "
            "Return a list sorted by score descending, "
            "then id ascending."
        ),
    )

    assert spec is not None
    assert spec["function_name"] == "choose_best"

    assert (
        "normalize_records"
        not in spec["test_source"]
    )

    assert (
        "benchmark_solution"
        not in spec["test_source"]
    )


def test_adaptive_tdd_consumes_explicit_record_contract():
    source = inspect.getsource(
        _python_adaptive_tdd_action
    )

    assert (
        "_explicit_record_function_contract"
        in source
    )

    assert (
        'test_source = explicit_contract["test_source"]'
        in source
    )

    assert (
        source.index(
            "_explicit_record_function_contract"
        )
        < source.index(
            "_adaptive_repair_source"
        )
    )
