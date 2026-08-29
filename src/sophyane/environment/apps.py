"""Environment application abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .model import (
    EnvironmentAction,
)
from .world import (
    ResearchEnvironment,
)


@dataclass(frozen=True)
class AppCall:
    app: str
    operation: str
    arguments: dict[str, Any]


class EnvironmentApp:
    def __init__(
        self,
        name: str,
    ) -> None:
        self.name = name
        self._operations: dict[
            str,
            Callable[
                [
                    ResearchEnvironment,
                    dict[str, Any],
                ],
                Any,
            ],
        ] = {}

    def register(
        self,
        operation: str,
        handler: Callable[
            [
                ResearchEnvironment,
                dict[str, Any],
            ],
            Any,
        ],
    ) -> None:
        self._operations[
            operation
        ] = handler

    def call(
        self,
        environment:
            ResearchEnvironment,
        operation: str,
        arguments:
            dict[str, Any],
    ) -> Any:
        if operation not in (
            self._operations
        ):
            raise KeyError(
                f"unknown {self.name} "
                f"operation: {operation}"
            )

        result = (
            self._operations[
                operation
            ](
                environment,
                arguments,
            )
        )

        environment.act(
            EnvironmentAction(
                actor=self.name,
                action=operation,
                payload={
                    "operation": "noop",
                    "arguments":
                        arguments,
                },
            )
        )

        return result


class AppRegistry:
    def __init__(
        self,
    ) -> None:
        self._apps: dict[
            str,
            EnvironmentApp,
        ] = {}

    def register(
        self,
        app: EnvironmentApp,
    ) -> None:
        self._apps[
            app.name
        ] = app

    def get(
        self,
        name: str,
    ) -> EnvironmentApp:
        return self._apps[
            name
        ]

    def names(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                self._apps
            )
        )
