"""Sophyane closed-loop discovery engine.

Objective
  -> knowledge
  -> hypotheses
  -> episodic adaptation
  -> candidates
  -> novelty
  -> experiment
  -> observation
  -> validation
  -> reproduction
  -> final novelty
  -> learning
"""
from __future__ import annotations

import json
import time

from pathlib import Path
from typing import Any, Iterable

from sophyane.discovery_contract import (
    Candidate,
    DiscoveryCandidateResult,
    DiscoveryEpisode,
    ExperimentPlan,
    Hypothesis,
    KnowledgeRecord,
    Observation,
    ValidationResult,
    new_episode_id,
    stable_id,
)
from sophyane.discovery_novelty import (
    novelty_passes,
    novelty_score,
)
from sophyane.discovery_runtime import (
    DiscoveryRuntime,
    discovery_runtime,
)


def _as_list(
    value: object,
) -> list[Any]:
    if isinstance(
        value,
        list,
    ):
        return value

    if isinstance(
        value,
        tuple,
    ):
        return list(
            value
        )

    return []


def _parse_payload(
    value: object,
) -> object:
    if isinstance(
        value,
        (
            dict,
            list,
        ),
    ):
        return value

    text = str(
        value
        or ""
    ).strip()

    if not text:
        return None

    if text.startswith(
        "```"
    ):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip()
            == "```"
        ):
            lines = lines[:-1]

        text = "\n".join(
            lines
        ).strip()

    try:
        return json.loads(
            text
        )
    except Exception:
        return text


def _knowledge_material(
    records: Iterable[
        KnowledgeRecord
    ],
) -> list[str]:
    return [
        item.content
        for item in records
        if str(
            item.content
            or ""
        ).strip()
    ]


def _generate_hypotheses(
    *,
    objective: str,
    knowledge: tuple[
        KnowledgeRecord,
        ...
    ],
    runtime: DiscoveryRuntime,
    limit: int,
) -> tuple[
    Hypothesis,
    ...
]:
    prompt = {
        "operation": (
            "generate_hypotheses"
        ),
        "objective": objective,
        "knowledge": [
            item.to_dict()
            for item
            in knowledge[:24]
        ],
        "requirements": {
            "maximum": limit,
            "prefer_falsifiable": True,
            "prefer_measurable_predictions": True,
            "avoid_claiming_novelty": True,
        },
        "return_schema": {
            "hypotheses": [
                {
                    "statement": "string",
                    "rationale": "string",
                    "predictions": [
                        "string"
                    ],
                    "assumptions": [
                        "string"
                    ],
                }
            ]
        },
    }

    raw = runtime.reason(
        "generate_hypotheses",
        prompt,
    )

    parsed = _parse_payload(
        raw
    )

    if isinstance(
        parsed,
        dict,
    ):
        values = _as_list(
            parsed.get(
                "hypotheses"
            )
        )
    elif isinstance(
        parsed,
        list,
    ):
        values = parsed
    elif isinstance(
        parsed,
        str,
    ):
        values = [
            {
                "statement": parsed,
            }
        ]
    else:
        values = []

    result = []

    for item in values[
        :max(
            1,
            int(limit),
        )
    ]:
        if isinstance(
            item,
            str,
        ):
            item = {
                "statement": item,
            }

        if not isinstance(
            item,
            dict,
        ):
            continue

        statement = str(
            item.get(
                "statement",
                "",
            )
            or ""
        ).strip()

        if not statement:
            continue

        result.append(
            Hypothesis(
                hypothesis_id=stable_id(
                    "hypothesis",
                    objective,
                    statement,
                ),
                statement=statement,
                rationale=str(
                    item.get(
                        "rationale",
                        "",
                    )
                    or ""
                ),
                predictions=tuple(
                    str(value)
                    for value
                    in _as_list(
                        item.get(
                            "predictions"
                        )
                    )
                    if str(
                        value
                    ).strip()
                ),
                assumptions=tuple(
                    str(value)
                    for value
                    in _as_list(
                        item.get(
                            "assumptions"
                        )
                    )
                    if str(
                        value
                    ).strip()
                ),
            )
        )

    return tuple(
        result
    )


def _generate_candidate(
    *,
    objective: str,
    hypothesis: Hypothesis,
    knowledge: tuple[
        KnowledgeRecord,
        ...
    ],
    runtime: DiscoveryRuntime,
) -> Candidate:
    raw = runtime.reason(
        "generate_candidate",
        {
            "operation": (
                "generate_candidate"
            ),
            "objective": objective,
            "hypothesis": (
                hypothesis.to_dict()
            ),
            "knowledge": [
                item.to_dict()
                for item
                in knowledge[:16]
            ],
            "requirements": {
                "concrete": True,
                "testable": True,
                "do_not_claim_novelty": True,
            },
            "return_schema": {
                "description": "string",
                "mechanism": "string",
                "expected_value": "string",
            },
        },
    )

    parsed = _parse_payload(
        raw
    )

    if isinstance(
        parsed,
        dict,
    ):
        description = str(
            parsed.get(
                "description",
                "",
            )
            or hypothesis.statement
        )

        mechanism = str(
            parsed.get(
                "mechanism",
                "",
            )
            or ""
        )

        expected_value = str(
            parsed.get(
                "expected_value",
                "",
            )
            or ""
        )
    else:
        description = str(
            parsed
            or hypothesis.statement
        )

        mechanism = ""
        expected_value = ""

    initial_score, reason = (
        novelty_score(
            description,
            _knowledge_material(
                knowledge
            ),
        )
    )

    return Candidate(
        candidate_id=stable_id(
            "candidate",
            hypothesis.hypothesis_id,
            description,
        ),
        hypothesis_id=(
            hypothesis.hypothesis_id
        ),
        description=description,
        mechanism=mechanism,
        expected_value=expected_value,
        novelty_score=initial_score,
        novelty_reason=reason,
    )


def _plan_experiment(
    *,
    objective: str,
    candidate: Candidate,
    runtime: DiscoveryRuntime,
) -> ExperimentPlan:
    raw = runtime.reason(
        "plan_experiment",
        {
            "operation": (
                "plan_experiment"
            ),
            "objective": objective,
            "candidate": (
                candidate.to_dict()
            ),
            "allowed_types": [
                "code",
                "simulation",
                "hardware_lab",
            ],
            "safety": {
                "hardware_lab_never_autonomous": True,
                "unsafe_code_never_autonomous": True,
            },
            "return_schema": {
                "experiment_type": (
                    "code|simulation|hardware_lab"
                ),
                "procedure": [
                    "string"
                ],
                "success_criteria": [
                    "string"
                ],
                "measurements": [
                    "string"
                ],
                "resources": [
                    "string"
                ],
                "safe_for_autonomous_execution": (
                    "boolean"
                ),
            },
        },
    )

    parsed = _parse_payload(
        raw
    )

    if not isinstance(
        parsed,
        dict,
    ):
        parsed = {}

    kind = str(
        parsed.get(
            "experiment_type",
            "simulation",
        )
        or "simulation"
    ).strip().casefold()

    safe = bool(
        parsed.get(
            "safe_for_autonomous_execution",
            False,
        )
    )

    if kind in {
        "hardware_lab",
        "hardware",
        "lab",
        "wet_lab",
        "physical",
    }:
        safe = False

    experiment_id = stable_id(
        "experiment",
        candidate.candidate_id,
        kind,
    )

    procedure = tuple(
        str(item)
        for item in _as_list(
            parsed.get(
                "procedure"
            )
        )
        if str(
            item
        ).strip()
    )

    criteria = tuple(
        str(item)
        for item in _as_list(
            parsed.get(
                "success_criteria"
            )
        )
        if str(
            item
        ).strip()
    )

    return ExperimentPlan(
        experiment_id=(
            experiment_id
        ),
        candidate_id=(
            candidate.candidate_id
        ),
        experiment_type=kind,
        procedure=procedure,
        success_criteria=criteria,
        measurements=tuple(
            str(item)
            for item in _as_list(
                parsed.get(
                    "measurements"
                )
            )
            if str(
                item
            ).strip()
        ),
        resources=tuple(
            str(item)
            for item in _as_list(
                parsed.get(
                    "resources"
                )
            )
            if str(
                item
            ).strip()
        ),
        safe_for_autonomous_execution=(
            safe
        ),
    )


def _validation_passes(
    validations: tuple[
        ValidationResult,
        ...
    ],
) -> bool:
    if not validations:
        return False

    passed = [
        item
        for item in validations
        if item.passed
    ]

    return bool(
        passed
    )


def _reproduce(
    *,
    plan: ExperimentPlan,
    first: Observation,
    runtime: DiscoveryRuntime,
    workspace: str,
) -> tuple[
    bool,
    Observation | None,
]:
    if not (
        first.executed
        and first.ok
        and plan.safe_for_autonomous_execution
    ):
        return (
            False,
            None,
        )

    if str(
        plan.experiment_type
    ).casefold() not in {
        "code",
        "simulation",
    }:
        return (
            False,
            None,
        )

    second = runtime.execute(
        plan,
        workspace,
    )

    reproduced = bool(
        second.executed
        and second.ok
    )

    return (
        reproduced,
        second,
    )


def run_discovery(
    objective: str,
    *,
    workspace: str | Path | None = None,
    runtime: DiscoveryRuntime | None = None,
    hypothesis_limit: int = 3,
    novelty_threshold: float = 0.35,
    learn: bool = True,
) -> DiscoveryEpisode:
    objective = str(
        objective
        or ""
    ).strip()

    if not objective:
        raise ValueError(
            "discovery objective is required"
        )

    root = Path(
        workspace
        or Path.cwd()
    ).expanduser().resolve()

    from sophyane.discovery_bridges import (
        initialize_discovery_bridges,
    )

    initialize_discovery_bridges()

    active_runtime = (
        runtime
        or discovery_runtime()
    )

    started = time.time()

    knowledge = active_runtime.retrieve(
        objective,
        str(root),
    )

    hypotheses = _generate_hypotheses(
        objective=objective,
        knowledge=knowledge,
        runtime=active_runtime,
        limit=hypothesis_limit,
    )

    results = []

    known_material = (
        _knowledge_material(
            knowledge
        )
    )

    for hypothesis in hypotheses:
        candidate = _generate_candidate(
            objective=objective,
            hypothesis=hypothesis,
            knowledge=knowledge,
            runtime=active_runtime,
        )

        if not novelty_passes(
            candidate.novelty_score,
            threshold=novelty_threshold,
        ):
            plan = ExperimentPlan(
                experiment_id=stable_id(
                    "experiment",
                    candidate.candidate_id,
                    "novelty_rejected",
                ),
                candidate_id=(
                    candidate.candidate_id
                ),
                experiment_type=(
                    "not_planned"
                ),
                procedure=(),
                success_criteria=(),
                safe_for_autonomous_execution=False,
            )

            observation = Observation(
                experiment_id=(
                    plan.experiment_id
                ),
                executed=False,
                ok=False,
                output="",
                evidence={
                    "reason": (
                        "INITIAL_NOVELTY_GATE_FAILED"
                    )
                },
            )

            results.append(
                DiscoveryCandidateResult(
                    candidate=candidate,
                    experiment=plan,
                    observation=observation,
                    validations=(),
                    reproduced=False,
                    final_novelty_score=(
                        candidate.novelty_score
                    ),
                    accepted=False,
                    rejection_reason=(
                        "INITIAL_NOVELTY_GATE_FAILED"
                    ),
                )
            )

            continue

        plan = _plan_experiment(
            objective=objective,
            candidate=candidate,
            runtime=active_runtime,
        )

        observation = (
            active_runtime.execute(
                plan,
                str(root),
            )
        )

        validations = (
            active_runtime.validate(
                plan,
                observation,
                str(root),
            )
        )

        reproduced, second = (
            _reproduce(
                plan=plan,
                first=observation,
                runtime=active_runtime,
                workspace=str(root),
            )
        )

        final_material = list(
            known_material
        )

        final_material.extend(
            [
                hypothesis.statement,
            ]
        )

        if second is not None:
            final_material.append(
                second.output
            )

        final_novelty, _ = (
            novelty_score(
                candidate.description,
                final_material,
            )
        )

        validation_ok = (
            _validation_passes(
                validations
            )
        )

        final_novel = (
            novelty_passes(
                final_novelty,
                threshold=novelty_threshold,
            )
        )

        accepted = bool(
            observation.executed
            and observation.ok
            and validation_ok
            and reproduced
            and final_novel
        )

        if accepted:
            rejection = ""
        elif not observation.executed:
            rejection = (
                "EXPERIMENT_NOT_EXECUTED"
            )
        elif not observation.ok:
            rejection = (
                "EXPERIMENT_FAILED"
            )
        elif not validation_ok:
            rejection = (
                "VALIDATION_FAILED"
            )
        elif not reproduced:
            rejection = (
                "REPRODUCTION_FAILED"
            )
        else:
            rejection = (
                "FINAL_NOVELTY_GATE_FAILED"
            )

        results.append(
            DiscoveryCandidateResult(
                candidate=candidate,
                experiment=plan,
                observation=observation,
                validations=validations,
                reproduced=reproduced,
                final_novelty_score=(
                    final_novelty
                ),
                accepted=accepted,
                rejection_reason=rejection,
            )
        )

    finished = time.time()

    episode = DiscoveryEpisode(
        episode_id=new_episode_id(
            objective
        ),
        objective=objective,
        knowledge=knowledge,
        hypotheses=hypotheses,
        results=tuple(
            results
        ),
        started_at=started,
        finished_at=finished,
        accepted_candidates=tuple(
            result.candidate.candidate_id
            for result in results
            if result.accepted
        ),
    )

    if learn:
        try:
            from sophyane.discovery_learning import (
                record_discovery_episode,
            )

            record_discovery_episode(
                episode,
                workspace=root,
            )
        except Exception:
            pass

    return episode


__all__ = [
    "run_discovery",
]
