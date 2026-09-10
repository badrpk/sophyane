from sophyane.benchmark_contract import (
    BenchmarkCapability,
    build_contract,
    validate_original_request_authority,
)


def test_original_request_requirement_cannot_be_made_optional():
    contract = build_contract(
        objective=(
            "build dog marketplace with service brokerage"
        ),
        benchmarks=(),
        capabilities=(
            BenchmarkCapability(
                capability_id="service.booking",
                title="Service booking",
                description="Book providers",
                original_request_required=True,
                benchmark_required=False,
            ),
        ),
    )

    ok, violations = (
        validate_original_request_authority(
            contract
        )
    )

    assert ok is False
    assert (
        "service.booking:"
        "original_request_marked_optional"
    ) in violations


def test_original_request_requirement_cannot_be_inapplicable():
    contract = build_contract(
        objective="build dog marketplace",
        benchmarks=(),
        capabilities=(
            BenchmarkCapability(
                capability_id="marketplace.search",
                title="Marketplace search",
                description="Search listings",
                original_request_required=True,
                applicable=False,
            ),
        ),
    )

    ok, violations = (
        validate_original_request_authority(
            contract
        )
    )

    assert ok is False
    assert any(
        "marked_inapplicable" in item
        for item in violations
    )
