"""Objective coding-contract registry for Sophyane adaptive TDD.

Concrete contract semantics live in coding_contract_nodes. This module owns registration, matching and the stable public API.
"""

from __future__ import annotations

from sophyane.coding_contract_nodes import (
    CodingContract,
    MedianContract,
    SortContract,
    builtin_coding_contracts,
)


class CodingContractRegistry:
    """Isolated deterministic registry of objective coding contracts."""

    def __init__(
        self,
    ) -> None:
        self._contracts: list[
            CodingContract
        ] = []

    def register(
        self,
        contract: CodingContract,
    ) -> None:
        """Register one contract exactly once by non-empty name."""
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
            for existing in self._contracts
        ):
            raise ValueError(
                f"Coding contract {name!r} is already registered"
            )

        self._contracts.append(
            contract
        )

    def snapshot(
        self,
    ) -> tuple[CodingContract, ...]:
        """Return an immutable deterministic snapshot."""
        return tuple(
            self._contracts
        )

    def match(
        self,
        request: str,
    ) -> CodingContract | None:
        """Return the highest-priority contract matching CURRENT request."""
        matches = [
            (
                int(
                    getattr(
                        contract,
                        "priority",
                        0,
                    )
                ),
                index,
                contract,
            )
            for index, contract in enumerate(
                self.snapshot()
            )
            if contract.matches(
                request
            )
        ]

        if not matches:
            return None

        # Highest priority wins. Registration order remains the deterministic
        # tie-breaker for contracts with equal priority.
        matches.sort(
            key=lambda item: (
                -item[0],
                item[1],
            )
        )

        return matches[0][2]


_DEFAULT_REGISTRY = (
    CodingContractRegistry()
)


def register_coding_contract(
    contract: CodingContract,
) -> None:
    """Compatibility API backed by the default registry."""
    _DEFAULT_REGISTRY.register(
        contract
    )


def registered_coding_contracts(
) -> tuple[CodingContract, ...]:
    """Compatibility API returning the default registry snapshot."""
    return _DEFAULT_REGISTRY.snapshot()


def load_builtin_coding_contracts(
    registry: CodingContractRegistry | None = None,
) -> CodingContractRegistry:
    """Load built-in contracts into the supplied or default registry."""
    target = (
        registry
        if registry is not None
        else _DEFAULT_REGISTRY
    )

    for contract in builtin_coding_contracts():
        target.register(
            contract
        )

    return target


load_builtin_coding_contracts(
    _DEFAULT_REGISTRY
)


def match_coding_contract(
    request: str,
) -> CodingContract | None:
    """Return the first deterministic contract node matching CURRENT request."""
    return _DEFAULT_REGISTRY.match(
        request
    )


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


def format_red_defect_guidance(
    *,
    request: str,
) -> str:
    """Return advisory deliberate-defect guidance from selected contract."""
    contract = match_coding_contract(
        request
    )

    if contract is None:
        return ""

    method = getattr(
        contract,
        "red_defect_guidance",
        None,
    )

    if not callable(method):
        return ""

    return str(
        method()
        or ""
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
