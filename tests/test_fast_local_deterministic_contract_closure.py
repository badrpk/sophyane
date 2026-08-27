from __future__ import annotations

import pytest

from sophyane.fast_local_coding import (
    _deterministic_contract_repair,
)


def _load(
    source: str,
) -> dict:
    namespace: dict = {}

    exec(
        compile(
            source,
            "<contract-test>",
            "exec",
        ),
        namespace,
    )

    return namespace


def test_materializes_generic_iterable_once() -> None:
    source = (
        "def average(items):\n"
        "    if not items:\n"
        "        return 0.0\n"
        "    return sum(items) / len(items)\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Fix average(items).\n"
                "- Accept any iterable.\n"
                "- Consume one-shot iterators only once.\n"
            ),
            source=source,
            failure=(
                "TypeError: object of type "
                "'generator' has no len()"
            ),
        )
    )

    assert repaired is not None
    assert "iterable-materialization" in reason

    namespace = _load(
        repaired
    )

    assert namespace[
        "average"
    ](
        (
            value
            for value in [2, 4, 6]
        )
    ) == 4.0


def test_does_not_materialize_without_request_authority() -> None:
    source = (
        "def average(items):\n"
        "    return sum(items) / len(items)\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Fix average(items)."
            ),
            source=source,
            failure=(
                "TypeError: object of type "
                "'generator' has no len()"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_explicit_int_conversion_replaces_narrow_type_guard() -> None:
    source = (
        "def can_supply(stock, request):\n"
        "    item, requested_amount = request\n"
        "    if not isinstance(requested_amount, int):\n"
        "        raise ValueError('integer required')\n"
        "    return stock.get(item, 0) >= requested_amount\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement can_supply(stock, request).\n"
                "- Convert amount to int.\n"
                "- Negative requested amounts raise ValueError.\n"
            ),
            source=source,
            failure=(
                "Failed: DID NOT RAISE ValueError"
            ),
        )
    )

    assert repaired is not None
    assert "explicit-int-contract" in reason

    namespace = _load(
        repaired
    )

    function = namespace[
        "can_supply"
    ]

    assert function(
        {"apple": 3},
        ("apple", "2"),
    )

    with pytest.raises(
        ValueError
    ):
        function(
            {"apple": 3},
            ("apple", "-1"),
        )

    with pytest.raises(
        ValueError
    ):
        function(
            {"apple": 3},
            ("apple", "bad"),
        )


def test_combines_int_conversion_and_iterable_materialization() -> None:
    source = (
        "def batches(items, width):\n"
        "    if width <= 0:\n"
        "        raise ValueError('bad width')\n"
        "    return [\n"
        "        items[i:i + width]\n"
        "        for i in range(0, len(items), width)\n"
        "    ]\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement batches(items, width).\n"
                "- Convert width to int.\n"
                "- Accept any iterable.\n"
                "- Raise ValueError when width <= 0.\n"
            ),
            source=source,
            failure=(
                "TypeError: object of type "
                "'generator' has no len()"
            ),
        )
    )

    assert repaired is not None
    assert "explicit-int-contract" in reason
    assert "iterable-materialization" in reason

    namespace = _load(
        repaired
    )

    function = namespace[
        "batches"
    ]

    assert function(
        (
            value
            for value in range(5)
        ),
        "2",
    ) == [
        [0, 1],
        [2, 3],
        [4],
    ]


def test_one_level_contract_removes_direct_recursive_extend() -> None:
    source = (
        "def expand_once(items):\n"
        "    result = []\n"
        "    for item in items:\n"
        "        if isinstance(item, (list, tuple)):\n"
        "            result.extend(expand_once(item))\n"
        "        else:\n"
        "            result.append(item)\n"
        "    return result\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement expand_once(items).\n"
                "- Flatten exactly one nesting level.\n"
                "- Lists and tuples should be expanded.\n"
                "- Other values remain atomic.\n"
            ),
            source=source,
            failure=(
                "AssertionError: "
                "assert [1, 2] == [[1], 2]"
            ),
        )
    )

    assert repaired is not None
    assert "bounded-one-level" in reason

    namespace = _load(
        repaired
    )

    assert namespace[
        "expand_once"
    ](
        [
            [[1]],
            [2],
        ]
    ) == [
        [1],
        2,
    ]


def test_one_level_repair_requires_explicit_contract() -> None:
    source = (
        "def expand(items):\n"
        "    result = []\n"
        "    for item in items:\n"
        "        if isinstance(item, list):\n"
        "            result.extend(expand(item))\n"
        "        else:\n"
        "            result.append(item)\n"
        "    return result\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement recursive expand(items)."
            ),
            source=source,
            failure=(
                "AssertionError"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_unrelated_source_is_unchanged() -> None:
    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Fix add(a, b)."
            ),
            source=(
                "def add(a, b):\n"
                "    return a + b\n"
            ),
            failure=(
                "AssertionError: assert 3 == 4"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_explicit_pair_availability_contract_closes_wrong_collection_shape() -> None:
    source = (
        "def enough(levels, order):\n"
        "    if not isinstance(order, list):\n"
        "        raise ValueError('order must be a list')\n"
        "    for entry in order:\n"
        "        label, amount = entry\n"
        "        if not isinstance(amount, int):\n"
        "            raise ValueError('integer required')\n"
        "    return True\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement enough(levels, order).\n"
                "- order is a (label, amount) pair.\n"
                "- Convert amount to int.\n"
                "- Missing entries count as zero.\n"
                "- Return True only when available stock is "
                ">= requested amount.\n"
                "- Negative requested amounts raise ValueError.\n"
            ),
            source=source,
            failure=(
                "ValueError: order must be a list; "
                "received tuple"
            ),
        )
    )

    assert repaired is not None
    assert (
        "explicit-pair-availability"
        in reason
    )

    namespace = _load(
        repaired
    )

    function = namespace[
        "enough"
    ]

    assert function(
        {
            "x": 3,
        },
        (
            "x",
            "2",
        ),
    )

    assert not function(
        {},
        (
            "x",
            "1",
        ),
    )

    assert function(
        {},
        (
            "x",
            0,
        ),
    )

    with pytest.raises(
        ValueError
    ):
        function(
            {
                "x": 3,
            },
            (
                "x",
                "-1",
            ),
        )

    with pytest.raises(
        ValueError
    ):
        function(
            {
                "x": 3,
            },
            (
                "x",
                "bad",
            ),
        )


def test_pair_availability_repair_requires_full_written_contract() -> None:
    source = (
        "def enough(levels, order):\n"
        "    if not isinstance(order, list):\n"
        "        raise ValueError('order must be a list')\n"
        "    return True\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement enough(levels, order).\n"
                "- order is a (label, amount) pair.\n"
                "- Convert amount to int.\n"
            ),
            source=source,
            failure=(
                "ValueError: order must be a list"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_pair_availability_repair_is_name_generic() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    for record in demand:\n"
        "        code, units = record\n"
        "    return False\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Convert units to int.\n"
                "- Missing capacity entries count as zero.\n"
                "- Return True only when available stock is "
                ">= requested quantity.\n"
                "- Negative requested quantities raise ValueError.\n"
            ),
            source=source,
            failure=(
                "TypeError: tuple contract was interpreted "
                "as a collection"
            ),
        )
    )

    assert repaired is not None
    assert (
        "explicit-pair-availability"
        in reason
    )

    namespace = _load(
        repaired
    )

    function = namespace[
        "permitted"
    ]

    assert function(
        {
            "A": 5,
        },
        (
            "A",
            "4",
        ),
    )

    assert not function(
        {},
        (
            "A",
            1,
        ),
    )


def test_pair_field_conversion_moves_before_negative_guard() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    if demand[1] < 0:\n"
        "        raise ValueError('negative')\n"
        "    units = int(demand[1])\n"
        "    if units == 0:\n"
        "        return True\n"
        "    return capacity.get(demand[0], 0) >= units\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Convert units to int.\n"
                "- Missing capacity entries count as zero.\n"
                "- Return True only when available stock is "
                ">= requested quantity.\n"
                "- Negative requested quantities raise ValueError.\n"
            ),
            source=source,
            failure=(
                "TypeError: '<' not supported between "
                "instances of 'str' and 'int'"
            ),
        )
    )

    assert repaired is not None

    assert (
        "pair-field-int-order"
        in reason
    )

    namespace = _load(
        repaired
    )

    function = namespace[
        "permitted"
    ]

    assert function(
        {
            "A": 5,
        },
        (
            "A",
            "4",
        ),
    )

    assert not function(
        {},
        (
            "A",
            "1",
        ),
    )

    assert function(
        {},
        (
            "A",
            0,
        ),
    )

    with pytest.raises(
        ValueError
    ):
        function(
            {
                "A": 3,
            },
            (
                "A",
                "-1",
            ),
        )

    with pytest.raises(
        ValueError
    ):
        function(
            {
                "A": 3,
            },
            (
                "A",
                "bad",
            ),
        )

    conversion = (
        "units = int(demand[1])"
    )

    guard = (
        "if units < 0:"
    )

    assert conversion in repaired
    assert guard in repaired

    assert (
        repaired.index(
            conversion
        )
        < repaired.index(
            guard
        )
    )


def test_pair_field_order_repair_is_name_generic() -> None:
    source = (
        "def allowed(levels, order):\n"
        "    if order[1] < 0:\n"
        "        raise ValueError('negative')\n"
        "    amount = int(order[1])\n"
        "    return levels.get(order[0], 0) >= amount\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement allowed(levels, order).\n"
                "- order is a (label, amount) pair.\n"
                "- Convert amount to int.\n"
                "- Missing entries count as zero.\n"
                "- Return True only when available stock is "
                ">= requested amount.\n"
                "- Negative requested amounts raise ValueError.\n"
            ),
            source=source,
            failure=(
                "TypeError: '<' not supported between "
                "instances of 'str' and 'int'"
            ),
        )
    )

    assert repaired is not None

    assert (
        "pair-field-int-order"
        in reason
    )

    function = _load(
        repaired
    )[
        "allowed"
    ]

    assert function(
        {
            "bolt": 8,
        },
        (
            "bolt",
            "6",
        ),
    )


def test_pair_field_order_requires_conversion_contract() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    if demand[1] < 0:\n"
        "        raise ValueError('negative')\n"
        "    units = int(demand[1])\n"
        "    return True\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Negative requested quantities raise ValueError.\n"
            ),
            source=source,
            failure=(
                "TypeError: '<' not supported between "
                "instances of 'str' and 'int'"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_pair_field_order_requires_negative_valueerror_contract() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    if demand[1] < 0:\n"
        "        return False\n"
        "    units = int(demand[1])\n"
        "    return True\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Convert units to int.\n"
            ),
            source=source,
            failure=(
                "TypeError: '<' not supported between "
                "instances of 'str' and 'int'"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_pair_field_order_does_not_fire_when_conversion_already_precedes_guard() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    units = int(demand[1])\n"
        "    if units < 0:\n"
        "        raise ValueError('negative')\n"
        "    return capacity.get(demand[0], 0) >= units\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Convert units to int.\n"
                "- Missing capacity entries count as zero.\n"
                "- Return True only when available stock is "
                ">= requested quantity.\n"
                "- Negative requested quantities raise ValueError.\n"
            ),
            source=source,
            failure=(
                "AssertionError"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_explicit_int_contract_recognizes_existing_int_expression_binding() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    units = int(demand[1])\n"
        "    return capacity.get(demand[0], 0) >= units\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Convert units to int.\n"
            ),
            source=source,
            failure=(
                "AssertionError"
            ),
        )
    )

    assert repaired is None
    assert reason == ""


def test_explicit_int_contract_does_not_duplicate_pair_field_conversion() -> None:
    source = (
        "def permitted(capacity, demand):\n"
        "    units = int(demand[1])\n"
        "    return units\n"
    )

    repaired, reason = (
        _deterministic_contract_repair(
            request=(
                "Implement permitted(capacity, demand).\n"
                "- demand is a (code, units) pair.\n"
                "- Convert units to int.\n"
            ),
            source=source,
            failure=(
                "AssertionError"
            ),
        )
    )

    assert repaired is None
    assert reason == ""

    assert source.count(
        "int("
    ) == 1
