"""Grounded HTTP scenarios extracted from generated project tests.

The verifier must never invent mutation payloads merely because an API route
exists. Mutation requests become mechanically executable only when generated
source/test code provides a concrete method, path and request body.

This module performs conservative static extraction only.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResponseBinding:
    name: str
    field: str


@dataclass(frozen=True)
class ApiScenarioStep:
    method: str
    path: str
    body: object | None = None
    expected_status: tuple[int, ...] = ()
    source: str = ""
    bindings: tuple[ResponseBinding, ...] = ()

    @property
    def bind(self) -> ResponseBinding | None:
        """Backward-compatible single-binding view."""
        if len(self.bindings) == 1:
            return self.bindings[0]

        return None


@dataclass(frozen=True)
class ApiScenario:
    name: str
    steps: tuple[ApiScenarioStep, ...]
    source: str = ""


_HTTP_METHODS = {
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
}


def _literal_value(
    node: ast.AST,
) -> object:
    """Return only values that are fully statically grounded."""

    if isinstance(
        node,
        ast.Constant,
    ):
        return node.value

    if isinstance(
        node,
        ast.Dict,
    ):
        result: dict[
            object,
            object,
        ] = {}

        for key_node, value_node in zip(
            node.keys,
            node.values,
        ):
            if key_node is None:
                raise ValueError(
                    "dictionary unpacking is not grounded"
                )

            key = _literal_value(
                key_node
            )

            value = _literal_value(
                value_node
            )

            result[
                key
            ] = value

        return result

    if isinstance(
        node,
        ast.List,
    ):
        return [
            _literal_value(
                item
            )
            for item in node.elts
        ]

    if isinstance(
        node,
        ast.Tuple,
    ):
        return tuple(
            _literal_value(
                item
            )
            for item in node.elts
        )

    if isinstance(
        node,
        ast.UnaryOp,
    ) and isinstance(
        node.op,
        ast.USub,
    ):
        value = _literal_value(
            node.operand
        )

        if isinstance(
            value,
            (
                int,
                float,
            ),
        ):
            return -value

    raise ValueError(
        "value is not statically grounded"
    )


def _string_literal(
    node: ast.AST,
) -> str | None:
    try:
        value = _literal_value(
            node
        )
    except ValueError:
        return None

    if not isinstance(
        value,
        str,
    ):
        return None

    return value



def _assigned_name(
    statement: ast.stmt,
) -> str | None:
    target: ast.AST | None = None

    if isinstance(
        statement,
        ast.Assign,
    ):
        if len(
            statement.targets
        ) != 1:
            return None

        target = statement.targets[
            0
        ]

    elif isinstance(
        statement,
        ast.AnnAssign,
    ):
        target = statement.target

    if isinstance(
        target,
        ast.Name,
    ):
        return target.id

    return None


def _binding_assignment(
    statement: ast.stmt,
    known_responses: set[str],
) -> tuple[
    ResponseBinding,
    str,
] | None:
    """Recognize:

        item_id = created["id"]

    where ``created`` is the result variable of an earlier grounded request.

    No attribute access, function calls, arithmetic, nested indexing or
    arbitrary Python evaluation is allowed.
    """

    name = _assigned_name(
        statement
    )

    if name is None:
        return None

    value: ast.AST | None = None

    if isinstance(
        statement,
        ast.Assign,
    ):
        value = statement.value

    elif isinstance(
        statement,
        ast.AnnAssign,
    ):
        value = statement.value

    if not isinstance(
        value,
        ast.Subscript,
    ):
        return None

    if not isinstance(
        value.value,
        ast.Name,
    ):
        return None

    if (
        value.value.id
        not in known_responses
    ):
        return None

    field_node = value.slice

    if isinstance(
        field_node,
        ast.Constant,
    ):
        field = field_node.value

    else:
        return None

    if not isinstance(
        field,
        str,
    ):
        return None

    field = field.strip()

    if not field:
        return None

    return (
        ResponseBinding(
            name=name,
            field=field,
        ),
        value.value.id,
    )


def _grounded_path_template(
    node: ast.AST,
    bindings: set[str],
) -> str | None:
    """Accept a literal /api path or a narrowly grounded f-string.

    Dynamic path pieces must be simple names previously established by a
    ResponseBinding. Expressions such as calls, attributes, arithmetic and
    format specifications fail closed.
    """

    literal = _string_literal(
        node
    )

    if literal is not None:
        return literal

    if not isinstance(
        node,
        ast.JoinedStr,
    ):
        return None

    parts: list[str] = []

    for value in node.values:
        if isinstance(
            value,
            ast.Constant,
        ):
            if not isinstance(
                value.value,
                str,
            ):
                return None

            parts.append(
                value.value
            )
            continue

        if not isinstance(
            value,
            ast.FormattedValue,
        ):
            return None

        if (
            value.conversion
            != -1
            or value.format_spec
            is not None
        ):
            return None

        if not isinstance(
            value.value,
            ast.Name,
        ):
            return None

        name = value.value.id

        if name not in bindings:
            return None

        parts.append(
            "{"
            + name
            + "}"
        )

    result = "".join(
        parts
    )

    if not result.startswith(
        "/api/"
    ):
        return None

    return result


def _request_call(
    node: ast.Call,
    *,
    bindings: set[str] | None = None,
) -> tuple[
    str,
    str,
    object | None,
] | None:
    """Recognize conservative HTTP client call shapes.

    Supported generated-test patterns include:

        self.request("POST", "/api/tasks", {...})
        client.request("PUT", "/api/tasks/1", body={...})
        connection.request("DELETE", "/api/tasks/1")

    Dynamic strings, interpolated IDs and computed bodies are rejected.
    """

    function = node.func

    if not isinstance(
        function,
        ast.Attribute,
    ):
        return None

    if function.attr != "request":
        return None

    if len(
        node.args
    ) < 2:
        return None

    method = _string_literal(
        node.args[
            0
        ]
    )

    path = _grounded_path_template(
        node.args[
            1
        ],
        bindings or set(),
    )

    if (
        method is None
        or path is None
    ):
        return None

    method = method.upper()

    if method not in _HTTP_METHODS:
        return None

    if not path.startswith(
        "/api/"
    ):
        return None

    body: object | None = None

    if len(
        node.args
    ) >= 3:
        try:
            body = _literal_value(
                node.args[
                    2
                ]
            )
        except ValueError:
            return None

    for keyword in node.keywords:
        if keyword.arg not in {
            "body",
            "json",
            "payload",
            "data",
        }:
            continue

        try:
            body = _literal_value(
                keyword.value
            )
        except ValueError:
            return None

    return (
        method,
        path,
        body,
    )


def _expected_status_from_assert(
    node: ast.Assert,
) -> tuple[int, ...]:
    """Recognize direct status assertions conservatively."""

    test = node.test

    if not isinstance(
        test,
        ast.Compare,
    ):
        return ()

    values: set[int] = set()

    for candidate in [
        test.left,
        *test.comparators,
    ]:
        if (
            isinstance(
                candidate,
                ast.Constant,
            )
            and isinstance(
                candidate.value,
                int,
            )
            and 100
            <= candidate.value
            <= 599
        ):
            values.add(
                int(
                    candidate.value
                )
            )

    return tuple(
        sorted(
            values
        )
    )


def _scenario_from_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    source_path: str,
) -> ApiScenario | None:
    steps: list[
        ApiScenarioStep
    ] = []

    statements = list(
        node.body
    )

    known_responses: set[str] = set()

    # SOPHYANE_GROUNDED_RESPONSE_PROVENANCE_V1
    #
    # A response variable must retain the exact scenario step that produced
    # it. A later binding such as `task_id = created["id"]` must attach to
    # the `created = request(...)` step, not merely to whichever request
    # happened most recently.
    response_steps: dict[
        str,
        int,
    ] = {}

    # SOPHYANE_GROUNDED_MULTI_BINDING_SHADOWING_V1
    #
    # `bindings` tracks only symbols whose provenance is still valid at the
    # current statement. Ordinary reassignment removes a symbol before later
    # dynamic request paths are analyzed.
    bindings: dict[
        str,
        ResponseBinding,
    ] = {}

    pending_bindings_for_step: dict[
        int,
        list[ResponseBinding],
    ] = {}

    for index, statement in enumerate(
        statements
    ):
        binding_result = _binding_assignment(
            statement,
            known_responses,
        )

        if binding_result is not None:
            (
                binding,
                response_name,
            ) = binding_result

            origin_step = response_steps.get(
                response_name
            )

            if origin_step is None:
                # Defensive fail-closed guard. _binding_assignment already
                # requires a known response, so this should not normally occur.
                continue

            # SOPHYANE_GROUNDED_BINDING_TRANSFER_V1
            #
            # A symbolic name has one active producer provenance at a time.
            # If the same name is rebound from a later grounded response,
            # remove its stale producer attachment before transferring
            # ownership to the new response step.
            for producer_step in list(
                pending_bindings_for_step
            ):
                remaining = [
                    existing
                    for existing
                    in pending_bindings_for_step[
                        producer_step
                    ]
                    if (
                        existing.name
                        != binding.name
                    )
                ]

                if remaining:
                    pending_bindings_for_step[
                        producer_step
                    ] = remaining

                else:
                    pending_bindings_for_step.pop(
                        producer_step,
                        None,
                    )

            bindings[
                binding.name
            ] = binding

            pending_bindings_for_step.setdefault(
                origin_step,
                [],
            ).append(
                binding
            )

            continue

        call: ast.Call | None = None

        result_name = _assigned_name(
            statement
        )

        # Any ordinary assignment to an already-grounded symbol shadows its
        # previous provenance. A recognized response-binding assignment above
        # has already continued, so reaching here means the symbol is no longer
        # justified by its former response field.
        if (
            result_name is not None
            and result_name in bindings
        ):
            bindings.pop(
                result_name,
                None,
            )

        if isinstance(
            statement,
            ast.Expr,
        ) and isinstance(
            statement.value,
            ast.Call,
        ):
            call = statement.value

        elif isinstance(
            statement,
            ast.Assign,
        ) and isinstance(
            statement.value,
            ast.Call,
        ):
            call = statement.value

        elif isinstance(
            statement,
            ast.AnnAssign,
        ) and isinstance(
            statement.value,
            ast.Call,
        ):
            call = statement.value

        if call is None:
            continue

        request = _request_call(
            call,
            bindings=set(
                bindings
            ),
        )

        if request is None:
            continue

        (
            method,
            path,
            body,
        ) = request

        expected_status: tuple[
            int,
            ...
        ] = ()

        if (
            index + 1
            < len(
                statements
            )
            and isinstance(
                statements[
                    index + 1
                ],
                ast.Assert,
            )
        ):
            expected_status = (
                _expected_status_from_assert(
                    statements[
                        index + 1
                    ]
                )
            )

        steps.append(
            ApiScenarioStep(
                method=method,
                path=path,
                body=body,
                expected_status=expected_status,
                source=source_path,
            )
        )

        if result_name is not None:
            known_responses.add(
                result_name
            )

            response_steps[
                result_name
            ] = (
                len(steps)
                - 1
            )

    if not steps:
        return None

    normalized_steps: list[
        ApiScenarioStep
    ] = []

    for index, step in enumerate(
        steps
    ):
        normalized_steps.append(
            ApiScenarioStep(
                method=step.method,
                path=step.path,
                body=step.body,
                expected_status=step.expected_status,
                source=step.source,
                bindings=tuple(
                    pending_bindings_for_step.get(
                        index,
                        (),
                    )
                ),
            )
        )

    return ApiScenario(
        name=node.name,
        steps=tuple(
            normalized_steps
        ),
        source=source_path,
    )


def discover_api_scenarios(
    workspace: Path,
) -> tuple[
    ApiScenario,
    ...
]:
    root = workspace.resolve()

    candidates: list[
        Path
    ] = []

    tests = root / "tests"

    if tests.is_dir():
        candidates.extend(
            sorted(
                tests.rglob(
                    "*.py"
                )
            )
        )

    values: list[
        ApiScenario
    ] = []

    for path in candidates:
        if not path.is_file():
            continue

        source = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        try:
            tree = ast.parse(
                source
            )

        except SyntaxError:
            continue

        relative = (
            path.relative_to(
                root
            ).as_posix()
        )

        for node in tree.body:
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            scenario = (
                _scenario_from_function(
                    node,
                    source_path=relative,
                )
            )

            if scenario is not None:
                values.append(
                    scenario
                )

    return tuple(
        values
    )


def scenario_summary(
    scenario: ApiScenario,
) -> str:
    rows = []

    for step in scenario.steps:
        body = ""

        if step.body is not None:
            body = (
                " body="
                + json.dumps(
                    step.body,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        expected = ""

        if step.expected_status:
            expected = (
                " expected="
                + ",".join(
                    str(
                        value
                    )
                    for value
                    in step.expected_status
                )
            )

        binding = ""

        if step.bindings:
            binding = (
                " bindings="
                + ",".join(
                    item.name
                    + "<-response."
                    + item.field
                    for item in step.bindings
                )
            )

        rows.append(
            f"{step.method} {step.path}"
            + body
            + expected
            + binding
        )

    return (
        scenario.name
        + ": "
        + " -> ".join(
            rows
        )
    )


__all__ = [
    "ApiScenario",
    "ApiScenarioStep",
    "ResponseBinding",
    "discover_api_scenarios",
    "scenario_summary",
]
