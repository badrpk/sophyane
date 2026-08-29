"""Environment-aware bounded Mode-3 RSI.

The existing run_supervised_mode3_nifdu_rsi() remains the candidate,
verification, held-out and NIFDU authority.

This module adds an external asynchronous scenario lifecycle around it.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Callable

from sophyane.environment import (
    CompositeVerifier,
    EnvironmentAction,
    ResearchEnvironment,
    Scenario,
    ScenarioResult,
    Verifier,
    save_trace,
)
from sophyane.mode3_meta_rsi import (
    choose_txq_policy,
)
from sophyane.recursive_evolution_controller import (
    run_supervised_mode3_nifdu_rsi,
)


MAX_ENVIRONMENT_RSI_STEPS = 12

_ACTION_PATTERN = re.compile(
    r"ENVIRONMENT_ACTION_JSON:\s*(\{.*\})",
    flags=re.DOTALL,
)


def _scenario_context(
    environment:
        ResearchEnvironment,
) -> str:
    payload = {
        "scenario_id":
            environment.scenario.scenario_id,
        "objective":
            environment.scenario.objective,
        "clock":
            environment.clock,
        "steps":
            environment.steps,
        # SOPHYANE_SKILL_STATE_MODEL_CONTEXT_V1
        #
        # Do not reconstruct the present from an ever-growing transcript.
        # The current explicit execution state plus latest observation is the
        # model-facing authority.
        #
        "execution_state":
            environment.execution_state.model_context(),
        "pending_events":
            environment.pending_events(),
        "environment_profile":
            asdict(
                environment.scenario.profile
            ),
    }

    return (
        "SOPHYANE_RESEARCH_ENVIRONMENT\n"
        + json.dumps(
            payload,
            sort_keys=True,
            default=str,
        )
        + "\n"
        "The world can change while you work. "
        "Do not assume the initial state remains current."
    )


def parse_environment_action(
    text: str,
) -> EnvironmentAction | None:
    match = _ACTION_PATTERN.search(
        str(
            text
            or ""
        )
    )

    if not match:
        return None

    decoder = json.JSONDecoder()

    try:
        raw, _ = decoder.raw_decode(
            match.group(
                1
            )
        )
    except Exception:
        return None

    if not isinstance(
        raw,
        dict,
    ):
        return None

    action = str(
        raw.get(
            "action",
            "",
        )
    ).strip()

    if not action:
        return None

    payload = raw.get(
        "payload",
        {},
    )

    if not isinstance(
        payload,
        dict,
    ):
        return None

    return EnvironmentAction(
        actor=str(
            raw.get(
                "actor",
                "sophyane",
            )
        ),
        action=action,
        payload=payload,
        at=(
            float(
                raw["at"]
            )
            if raw.get(
                "at"
            )
            is not None
            else None
        ),
    )


def run_environment_mode3_rsi(
    *,
    scenario: Scenario,
    repository: Path,
    verifier: Verifier,
    max_environment_steps: int = 4,
    mode3_iterations_per_step: int = 1,
    tick_seconds: float = 5.0,
    local_provider=None,
    nifdu_reviewer=None,
    controller=None,
    action_interpreter:
        Callable[
            [str],
            EnvironmentAction | None,
        ] | None = None,
    trace_directory: Path | None = None,
) -> ScenarioResult:
    """Run one bounded dynamic scenario.

    Lifetime learning can happen across repeated invocations.
    A single invocation remains bounded.
    """

    environment = (
        ResearchEnvironment(
            scenario
        )
    )

    steps = max(
        1,
        min(
            MAX_ENVIRONMENT_RSI_STEPS,
            int(
                max_environment_steps
            ),
        ),
    )

    inner_iterations = max(
        1,
        min(
            4,
            int(
                mode3_iterations_per_step
            ),
        ),
    )

    interpret = (
        action_interpreter
        or parse_environment_action
    )

    verification = verifier.verify(
        environment
    )

    stop_reason = (
        "initially_satisfied"
        if verification.ok
        else ""
    )

    for _ in range(
        steps
    ):
        if verification.ok:
            break

        if environment.finished():
            stop_reason = (
                "environment_budget"
            )
            break

        #
        # Environment evolves before the next reasoning step.
        #
        environment.advance(
            tick_seconds
        )

        txq = choose_txq_policy(
            scenario.objective,
            evolution_context=(
                _scenario_context(
                    environment
                )
            ),
            environment_profile=(
                scenario.profile
            ),
        )

        environment_objective = (
            scenario.objective
            + "\n\n"
            + _scenario_context(
                environment
            )
            + "\n"
            + "ENVIRONMENT_TXQ="
            + json.dumps(
                asdict(
                    txq
                ),
                sort_keys=True,
                default=str,
            )
            + "\n"
            + "If the scenario requires a world action, append exactly one "
            + "ENVIRONMENT_ACTION_JSON object with keys actor/action/payload/at."
        )

        result = (
            run_supervised_mode3_nifdu_rsi(
                objective=(
                    environment_objective
                ),
                repository=Path(
                    repository
                ),
                max_iterations=(
                    inner_iterations
                ),
                local_provider=(
                    local_provider
                ),
                nifdu_reviewer=(
                    nifdu_reviewer
                ),
                controller=controller,
            )
        )

        if result.iterations:
            last = (
                result.iterations[-1]
            )

            candidate_text = (
                str(
                    last.mode3_response
                    or ""
                )
                + "\n"
                + str(
                    last.review_response
                    or ""
                )
            )

            action = interpret(
                candidate_text
            )

            if action is not None:
                environment.act(
                    action
                )

        verification = verifier.verify(
            environment
        )

        if verification.ok:
            stop_reason = (
                "verified"
            )
            break

        if not result.success:
            stop_reason = (
                result.stop_reason
                or "mode3_unsolved"
            )

    trace_path = ""

    if trace_directory is not None:
        target = (
            Path(
                trace_directory
            )
            / (
                scenario.scenario_id
                + ".json"
            )
        )

        trace_path = str(
            save_trace(
                environment,
                target,
            )
        )

    if not stop_reason:
        stop_reason = (
            "verified"
            if verification.ok
            else "step_budget"
        )

    return ScenarioResult(
        scenario_id=(
            scenario.scenario_id
        ),
        success=verification.ok,
        score=verification.score,
        final_clock=(
            environment.clock
        ),
        steps=environment.steps,
        verification=verification,
        trace_path=trace_path,
        stop_reason=stop_reason,
    )


__all__ = [
    "MAX_ENVIRONMENT_RSI_STEPS",
    "parse_environment_action",
    "run_environment_mode3_rsi",
]
