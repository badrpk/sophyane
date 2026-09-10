from sophyane.benchmark_contract import (
    BenchmarkCapability,
    BenchmarkReference,
    build_contract,
)


def test_contract_is_deterministic():
    benchmark = BenchmarkReference(
        benchmark_id="akc",
        name="AKC Marketplace",
        url="https://marketplace.akc.org/",
        role="marketplace",
        capabilities=(
            "puppy.search",
            "breeder.profile",
        ),
    )

    capability = BenchmarkCapability(
        capability_id="puppy.search",
        title="Puppy search",
        description="Search available puppies",
        source_benchmarks=("akc",),
        verification_steps=(
            "enter breed query",
            "verify result changes",
        ),
        required_evidence=(
            "interaction",
            "render",
        ),
    )

    a = build_contract(
        objective="build comprehensive dog marketplace",
        benchmarks=(benchmark,),
        capabilities=(capability,),
    )

    b = build_contract(
        objective="build comprehensive dog marketplace",
        benchmarks=(benchmark,),
        capabilities=(capability,),
    )

    assert a.contract_hash == b.contract_hash
    assert len(a.contract_hash) == 64


def test_contract_rejects_more_than_three_primary_benchmarks():
    import pytest

    refs = tuple(
        BenchmarkReference(
            benchmark_id=str(i),
            name=f"Benchmark {i}",
            url=f"https://example.com/{i}",
            role="marketplace",
        )
        for i in range(4)
    )

    with pytest.raises(ValueError):
        build_contract(
            objective="dog marketplace",
            benchmarks=refs,
            capabilities=(),
        )
