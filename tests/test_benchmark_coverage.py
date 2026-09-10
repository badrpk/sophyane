from sophyane.benchmark_contract import (
    BenchmarkCapability,
    build_contract,
)
from sophyane.benchmark_coverage import (
    CapabilityEvidence,
    benchmark_gate_passes,
    evaluate_coverage,
)


def contract():
    return build_contract(
        objective="comprehensive dog platform",
        benchmarks=(),
        capabilities=(
            BenchmarkCapability(
                capability_id="puppy.search",
                title="Puppy search",
                description="Search puppies",
                required_evidence=(
                    "interaction",
                    "render",
                ),
            ),
            BenchmarkCapability(
                capability_id="favorites.persist",
                title="Favorites persistence",
                description="Persist favorites",
                required_evidence=(
                    "interaction",
                    "persistence",
                ),
            ),
            BenchmarkCapability(
                capability_id="live.payment",
                title="Real payment",
                description="Actual external payment",
                applicable=False,
                implementation="external_integration",
                backend_required_for_live_use=True,
                required_evidence=(
                    "external",
                ),
            ),
        ),
    )


def test_full_verified_coverage_passes_gate():
    result = evaluate_coverage(
        contract(),
        (
            CapabilityEvidence(
                capability_id="puppy.search",
                implemented=True,
                workflow_passed=True,
                evidence=(
                    "interaction",
                    "render",
                ),
            ),
            CapabilityEvidence(
                capability_id="favorites.persist",
                implemented=True,
                workflow_passed=True,
                evidence=(
                    "interaction",
                    "persistence",
                ),
            ),
        ),
    )

    assert result.applicable == 2
    assert result.implemented == 2
    assert result.verified == 2
    assert result.coverage == 1.0
    assert result.workflow_coverage == 1.0
    assert benchmark_gate_passes(result) is True


def test_implemented_without_required_evidence_is_not_verified():
    result = evaluate_coverage(
        contract(),
        (
            CapabilityEvidence(
                capability_id="puppy.search",
                implemented=True,
                workflow_passed=True,
                evidence=("interaction",),
            ),
            CapabilityEvidence(
                capability_id="favorites.persist",
                implemented=True,
                workflow_passed=True,
                evidence=(
                    "interaction",
                    "persistence",
                ),
            ),
        ),
    )

    assert result.implemented == 2
    assert result.verified == 1
    assert result.coverage == 0.5
    assert "puppy.search" in result.unverified_capabilities
    assert benchmark_gate_passes(result) is False


def test_missing_capability_fails_gate():
    result = evaluate_coverage(
        contract(),
        (
            CapabilityEvidence(
                capability_id="puppy.search",
                implemented=True,
                workflow_passed=True,
                evidence=(
                    "interaction",
                    "render",
                ),
            ),
        ),
    )

    assert "favorites.persist" in result.missing_capabilities
    assert benchmark_gate_passes(result) is False
