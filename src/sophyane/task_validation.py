"""Validate outputs produced by Sophyane compiled tasks."""

from __future__ import annotations

from typing import Any

from sophyane.task_compiler import (
    CompiledTask,
)


_TYPES = {
    "bool": bool,
    "str": str,
    "int": int,
    "list": list,
    "dict": dict,
}


def validate_task_result(
    task: CompiledTask,
    payload: Any,
) -> list[str]:
    if not isinstance(
        payload,
        dict,
    ):
        return [
            "payload_not_object"
        ]

    errors = []

    for key, expected_name in (
        task.expected_schema.items()
    ):
        if key not in payload:
            errors.append(
                f"missing:{key}"
            )

            continue

        expected_type = (
            _TYPES.get(
                expected_name
            )
        )

        if (
            expected_type
            and not isinstance(
                payload[key],
                expected_type,
            )
        ):
            errors.append(
                f"type:{key}:"
                f"expected_{expected_name}"
            )

    if payload.get("ok") is not True:
        errors.append(
            "payload_ok_false"
        )

    return errors


__all__ = [
    "validate_task_result",
]
