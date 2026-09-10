from sophyane.benchmark_contract import (
    BenchmarkReference,
)
from sophyane.benchmark_discovery import (
    BenchmarkCandidate,
    select_complementary_benchmarks,
)


def candidate(
    *,
    benchmark_id,
    role,
    capabilities,
    score,
):
    return BenchmarkCandidate(
        reference=BenchmarkReference(
            benchmark_id=benchmark_id,
            name=benchmark_id,
            url="https://example.com/" + benchmark_id,
            role=role,
            capabilities=tuple(capabilities),
        ),
        domain_similarity=score,
        workflow_similarity=score,
        product_model_similarity=score,
        design_quality=score,
    )


def test_selection_prefers_complementary_capability_coverage():
    candidates = (
        candidate(
            benchmark_id="market-a",
            role="marketplace",
            capabilities=(
                "puppy.search",
                "breeder.profile",
                "favorites",
            ),
            score=1.0,
        ),
        candidate(
            benchmark_id="market-copy",
            role="marketplace",
            capabilities=(
                "puppy.search",
                "breeder.profile",
                "favorites",
            ),
            score=0.99,
        ),
        candidate(
            benchmark_id="services",
            role="service_brokerage",
            capabilities=(
                "provider.search",
                "booking",
                "messaging",
            ),
            score=0.90,
        ),
        candidate(
            benchmark_id="adoption",
            role="adoption",
            capabilities=(
                "adoption.search",
                "rescue.profile",
                "application",
            ),
            score=0.89,
        ),
    )

    selected = select_complementary_benchmarks(
        candidates,
        limit=3,
    )

    ids = {
        item.benchmark_id
        for item in selected
    }

    assert "market-a" in ids
    assert "services" in ids
    assert "adoption" in ids
    assert "market-copy" not in ids
