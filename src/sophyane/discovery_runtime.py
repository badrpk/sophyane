"""Runtime adapters for the Sophyane Discovery Engine.

The engine depends on typed capabilities instead of hardcoding providers,
repositories, laboratories, simulators, or judges.
"""
from __future__ import annotations

import inspect
import json
import threading

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from sophyane.discovery_contract import (
    ExperimentPlan,
    KnowledgeRecord,
    Observation,
    ValidationResult,
)


KnowledgeRetriever = Callable[
    [str, str],
    Iterable[KnowledgeRecord],
]

Reasoner = Callable[
    [str, dict[str, Any]],
    Any,
]

ExperimentExecutor = Callable[
    [ExperimentPlan, str],
    Observation,
]

Validator = Callable[
    [
        ExperimentPlan,
        Observation,
        str,
    ],
    ValidationResult,
]


@dataclass(frozen=True)
class RuntimeStatus:
    knowledge_retrievers: tuple[str, ...]
    reasoners: tuple[str, ...]
    executors: tuple[str, ...]
    validators: tuple[str, ...]


class DiscoveryRuntime:
    def __init__(self) -> None:
        self._knowledge: dict[
            str,
            KnowledgeRetriever,
        ] = {}

        self._reasoners: dict[
            str,
            Reasoner,
        ] = {}

        self._executors: dict[
            str,
            ExperimentExecutor,
        ] = {}

        self._validators: dict[
            str,
            Validator,
        ] = {}

        self._lock = (
            threading.RLock()
        )

    def register_knowledge_retriever(
        self,
        name: str,
        callback: KnowledgeRetriever,
    ) -> None:
        with self._lock:
            self._knowledge[
                str(name)
            ] = callback

    def register_reasoner(
        self,
        name: str,
        callback: Reasoner,
    ) -> None:
        with self._lock:
            self._reasoners[
                str(name)
            ] = callback

    def register_executor(
        self,
        experiment_type: str,
        callback: ExperimentExecutor,
    ) -> None:
        with self._lock:
            self._executors[
                str(
                    experiment_type
                ).casefold()
            ] = callback

    def register_validator(
        self,
        name: str,
        callback: Validator,
    ) -> None:
        with self._lock:
            self._validators[
                str(name)
            ] = callback

    def retrieve(
        self,
        objective: str,
        workspace: str,
    ) -> tuple[
        KnowledgeRecord,
        ...
    ]:
        records: list[
            KnowledgeRecord
        ] = []

        with self._lock:
            callbacks = tuple(
                self._knowledge.items()
            )

        for name, callback in callbacks:
            try:
                values = callback(
                    objective,
                    workspace,
                )
            except Exception as exc:
                records.append(
                    KnowledgeRecord(
                        source=name,
                        kind="retrieval_error",
                        content=str(exc),
                        score=0.0,
                    )
                )

                continue

            for item in values or ():
                if isinstance(
                    item,
                    KnowledgeRecord,
                ):
                    records.append(
                        item
                    )

        return tuple(
            records
        )

    def reason(
        self,
        task: str,
        context: dict[str, Any],
    ) -> Any:
        with self._lock:
            callbacks = tuple(
                self._reasoners.items()
            )

        errors = []

        for name, callback in callbacks:
            try:
                result = callback(
                    task,
                    context,
                )
            except Exception as exc:
                errors.append(
                    f"{name}: {exc}"
                )
                continue

            if result not in (
                None,
                "",
                [],
                {},
            ):
                return result

        if errors:
            raise RuntimeError(
                "DISCOVERY_REASONER_FAILED: "
                + " | ".join(
                    errors
                )
            )

        raise RuntimeError(
            "DISCOVERY_REASONER_UNAVAILABLE"
        )

    def execute(
        self,
        plan: ExperimentPlan,
        workspace: str,
    ) -> Observation:
        experiment_type = str(
            plan.experiment_type
            or ""
        ).casefold()

        # Physical-world work is never executed implicitly.
        if experiment_type in {
            "hardware",
            "hardware_lab",
            "lab",
            "wet_lab",
            "physical",
        }:
            return Observation(
                experiment_id=(
                    plan.experiment_id
                ),
                executed=False,
                ok=False,
                output=(
                    "Physical experiment requires "
                    "explicit external execution."
                ),
                evidence={
                    "reason": (
                        "PHYSICAL_EXECUTION_REQUIRES_EXTERNAL_OPERATOR"
                    )
                },
            )

        if not (
            plan.safe_for_autonomous_execution
        ):
            return Observation(
                experiment_id=(
                    plan.experiment_id
                ),
                executed=False,
                ok=False,
                output=(
                    "Experiment was not marked safe "
                    "for autonomous execution."
                ),
                evidence={
                    "reason": (
                        "AUTONOMOUS_EXECUTION_NOT_AUTHORIZED"
                    )
                },
            )

        with self._lock:
            callback = self._executors.get(
                experiment_type
            )

        if callback is None:
            return Observation(
                experiment_id=(
                    plan.experiment_id
                ),
                executed=False,
                ok=False,
                output="",
                evidence={
                    "reason": (
                        "EXPERIMENT_EXECUTOR_UNAVAILABLE"
                    )
                },
            )

        return callback(
            plan,
            workspace,
        )

    def validate(
        self,
        plan: ExperimentPlan,
        observation: Observation,
        workspace: str,
    ) -> tuple[
        ValidationResult,
        ...
    ]:
        with self._lock:
            callbacks = tuple(
                self._validators.items()
            )

        results = []

        for name, callback in callbacks:
            try:
                result = callback(
                    plan,
                    observation,
                    workspace,
                )
            except Exception as exc:
                result = ValidationResult(
                    validator=name,
                    passed=False,
                    score=0.0,
                    summary=str(exc),
                    evidence={
                        "validator_error": True,
                    },
                )

            if isinstance(
                result,
                ValidationResult,
            ):
                results.append(
                    result
                )

        return tuple(
            results
        )

    def status(self) -> RuntimeStatus:
        with self._lock:
            return RuntimeStatus(
                knowledge_retrievers=tuple(
                    sorted(
                        self._knowledge
                    )
                ),
                reasoners=tuple(
                    sorted(
                        self._reasoners
                    )
                ),
                executors=tuple(
                    sorted(
                        self._executors
                    )
                ),
                validators=tuple(
                    sorted(
                        self._validators
                    )
                ),
            )


_RUNTIME = DiscoveryRuntime()


def discovery_runtime() -> DiscoveryRuntime:
    return _RUNTIME


__all__ = [
    "DiscoveryRuntime",
    "RuntimeStatus",
    "discovery_runtime",
]
