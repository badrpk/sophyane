"""Shared primitives for objective coding-contract nodes."""

from __future__ import annotations

import ast
from typing import Protocol


class CodingContract(Protocol):
    """Interface implemented by deterministic coding-contract nodes."""

    name: str
    priority: int

    def matches(
        self,
        request: str,
    ) -> bool:
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

    def red_defect_guidance(
        self,
    ) -> str:
        ...

    def preflight_constraints(
        self,
    ) -> str:
        ...

    def corrective_constraints(
        self,
        *,
        last_error: str = "",
        execution_feedback: str = "",
    ) -> str:
        ...


def _normalized_request(
    request: str,
) -> str:
    return " ".join(
        str(request or "")
        .casefold()
        .split()
    )


def _called_function_name(
    call: ast.Call,
) -> str | None:
    """Return terminal name for direct or module-qualified calls."""
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
