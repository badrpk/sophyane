from sophyane.discovery_contract import (
    ExperimentPlan,
    Observation,
)


def _plan(
    *,
    kind,
    safe,
):
    return ExperimentPlan(
        experiment_id="exp-1",
        candidate_id="cand-1",
        experiment_type=kind,
        procedure=("run",),
        success_criteria=("passes",),
        safe_for_autonomous_execution=safe,
    )


def test_hardware_lab_never_executes_automatically(
    tmp_path,
):
    from sophyane.discovery_runtime import (
        DiscoveryRuntime,
    )

    runtime = DiscoveryRuntime()

    runtime.register_executor(
        "hardware_lab",
        lambda *args: (_ for _ in ()).throw(
            AssertionError(
                "hardware must not execute"
            )
        ),
    )

    result = runtime.execute(
        _plan(
            kind="hardware_lab",
            safe=True,
        ),
        str(tmp_path),
    )

    assert result.executed is False

    assert (
        result.evidence[
            "reason"
        ]
        == (
            "PHYSICAL_EXECUTION_REQUIRES_EXTERNAL_OPERATOR"
        )
    )


def test_safe_simulation_can_use_registered_executor(
    tmp_path,
):
    from sophyane.discovery_runtime import (
        DiscoveryRuntime,
    )

    runtime = DiscoveryRuntime()

    runtime.register_executor(
        "simulation",
        lambda plan, workspace: Observation(
            experiment_id=(
                plan.experiment_id
            ),
            executed=True,
            ok=True,
            output="simulation passed",
            evidence={
                "tests_passed": True,
            },
        ),
    )

    result = runtime.execute(
        _plan(
            kind="simulation",
            safe=True,
        ),
        str(tmp_path),
    )

    assert result.executed is True
    assert result.ok is True
