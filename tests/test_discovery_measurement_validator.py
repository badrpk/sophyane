from sophyane.discovery_bridges import (
    _deterministic_validator,
)
from sophyane.discovery_contract import (
    ExperimentPlan,
    Observation,
)


def make_plan():
    return ExperimentPlan(
        experiment_id="experiment",
        candidate_id="candidate",
        experiment_type="simulation",
        procedure=("test",),
        success_criteria=("pass",),
        safe_for_autonomous_execution=True,
    )


def make_observation(
    evidence,
    *,
    executed=True,
    ok=True,
):
    return Observation(
        experiment_id="experiment",
        executed=executed,
        ok=ok,
        output="",
        measurements={
            "baseline_score": 1,
            "candidate_score": 2,
        },
        evidence=dict(evidence),
    )


def test_deterministic_measurement_evidence_passes():
    result = _deterministic_validator(
        make_plan(),
        make_observation(
            {
                "deterministic_verified": True,
            }
        ),
        ".",
    )

    assert result.passed is True


def test_tests_passed_flag_alone_does_not_pass():
    result = _deterministic_validator(
        make_plan(),
        make_observation(
            {
                "tests_passed": True,
            }
        ),
        ".",
    )

    assert result.passed is False


def test_generic_verified_flag_alone_does_not_pass():
    result = _deterministic_validator(
        make_plan(),
        make_observation(
            {
                "verified": True,
            }
        ),
        ".",
    )

    assert result.passed is False


def test_byte_for_byte_flag_alone_does_not_pass():
    result = _deterministic_validator(
        make_plan(),
        make_observation(
            {
                "byte_for_byte_verified": True,
            }
        ),
        ".",
    )

    assert result.passed is False


def test_failed_execution_cannot_pass():
    result = _deterministic_validator(
        make_plan(),
        make_observation(
            {
                "deterministic_verified": True,
            },
            ok=False,
        ),
        ".",
    )

    assert result.passed is False
