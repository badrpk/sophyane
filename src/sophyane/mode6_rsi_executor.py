"""Explicit, fail-closed Mode-6 to RSI execution bridge."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from typing import Any, Sequence

from sophyane.human_conversation import ImprovementObservation
from sophyane.rsi.models import WeaknessRecord


def _text(value: Any) -> str:
    return str(value or "").strip()


def observation_to_weakness(
    observation: ImprovementObservation,
    *,
    baseline_commit: str,
    verification_commands: Sequence[Sequence[str]] = (("pytest", "-q"),),
    target_metric: str | None = None,
    required_improvement: float = 1.0,
) -> WeaknessRecord:
    """Convert grounded diagnostic evidence to the existing RSI input type."""
    if not isinstance(observation, ImprovementObservation):
        raise ValueError("observation type is not grounded")
    if observation.trusted or observation.instruction_authority or observation.mutation_authority:
        raise ValueError("observation has authority")
    problem = _text(observation.problem)
    component = _text(observation.component)
    evidence = tuple(_text(item) for item in observation.evidence)
    if not problem or not component or not evidence or not all(evidence):
        raise ValueError("grounded weakness evidence is incomplete")
    if not _text(baseline_commit):
        raise ValueError("baseline commit is required")
    commands = tuple(tuple(str(token) for token in command) for command in verification_commands)
    if not commands or not all(commands):
        raise ValueError("verification commands are required")
    if required_improvement <= 0:
        raise ValueError("required improvement must be positive")
    identifier = hashlib.sha256((component + "\0" + problem + "\0" + "\0".join(evidence)).encode()).hexdigest()[:24]
    return WeaknessRecord(
        weakness_id="mode6-" + identifier,
        description=problem,
        evidence=evidence,
        baseline_commit=_text(baseline_commit),
        target_metric=_text(target_metric) or component,
        baseline_value=0.0,
        required_improvement=float(required_improvement),
        protected_metrics={},
        verification_commands=commands,
        direction="higher",
    )


def run_once_explicit(
    observation: ImprovementObservation,
    *,
    controller: Any,
    baseline_commit: str,
    parent_iteration: str | None = None,
    **weakness_options: Any,
) -> dict[str, Any]:
    """Run one guarded iteration only when the caller explicitly asks."""
    weakness = observation_to_weakness(observation, baseline_commit=baseline_commit, **weakness_options)
    result = controller.run_once(weakness, parent_iteration=parent_iteration)
    state = getattr(result, "state", None)
    evidence = dict(getattr(result, "evidence", {}) or {})
    evidence.update({"observation": asdict(observation), "weakness": asdict(weakness)})
    return {"ok": state not in ("REJECTED", "NO_ACTION"),
            "state": getattr(state, "value", state),
            "iteration_id": getattr(result, "iteration_id", None), "evidence": evidence}


__all__ = ["observation_to_weakness", "run_once_explicit"]
