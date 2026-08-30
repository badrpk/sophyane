from __future__ import annotations

import pytest

from sophyane.local_coding_capability import (
    _validate_generated_python,
)


def test_validator_allows_get_on_local_dict_literal() -> None:
    source = """def lookup(key):
    values = {"a": 1}
    return values.get(key)
"""

    _validate_generated_python(
        source,
        function_name="lookup",
        is_test=False,
        module_name="sample",
    )


def test_validator_allows_get_on_local_dict_constructor() -> None:
    source = """def lookup(items, key):
    values = dict(items)
    return values.get(key)
"""

    _validate_generated_python(
        source,
        function_name="lookup",
        is_test=False,
        module_name="sample",
    )


def test_validator_blocks_get_on_unknown_receiver() -> None:
    source = """def fetch(client):
    return client.get("value")
"""

    with pytest.raises(
        ValueError,
        match="blocked side-effect call",
    ):
        _validate_generated_python(
            source,
            function_name="fetch",
            is_test=False,
            module_name="sample",
        )


def test_validator_blocks_get_on_function_parameter_named_dict() -> None:
    source = """def fetch(mapping):
    return mapping.get("value")
"""

    with pytest.raises(
        ValueError,
        match="blocked side-effect call",
    ):
        _validate_generated_python(
            source,
            function_name="fetch",
            is_test=False,
            module_name="sample",
        )
