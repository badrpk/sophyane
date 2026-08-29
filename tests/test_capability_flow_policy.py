from sophyane.capability_flow_policy import (
    CapabilityDescriptor,
    LabeledValue,
    Sensitivity,
    combine_labels,
    evaluate_capability_input,
)


def test_transformation_preserves_secret_taint():
    original = LabeledValue.create(
        "token-value",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "credential",
        },
        origin="local-vault",
    )

    image = original.transformed(
        b"png-bytes",
        capability="image_render",
        operation="render",
    )

    decoded = image.transformed(
        "token-value",
        capability="ocr_decode",
        operation="ocr",
    )

    assert (
        decoded.label.sensitivity
        == Sensitivity.AUTH_SECRET
    )

    assert (
        "credential"
        in decoded.label.categories
    )

    assert (
        "local-vault"
        in decoded.label.origin_ids
    )

    assert (
        len(
            decoded.label.provenance
        )
        == 2
    )


def test_external_sink_rejects_credentials():
    descriptor = CapabilityDescriptor(
        capability_id="external",
        maximum_input_sensitivity=(
            Sensitivity.SYSTEM_SECRET
        ),
        external_sink=True,
    )

    value = LabeledValue.create(
        "secret",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "credential",
        },
    )

    decision = (
        evaluate_capability_input(
            descriptor,
            value,
        )
    )

    assert decision.allowed is False


def test_public_information_can_flow_external():
    descriptor = CapabilityDescriptor(
        capability_id="search",
        maximum_input_sensitivity=(
            Sensitivity.INTERNAL
        ),
        external_sink=True,
    )

    value = LabeledValue.create(
        "weather forecast",
        sensitivity=Sensitivity.PUBLIC,
    )

    assert (
        evaluate_capability_input(
            descriptor,
            value,
        ).allowed
        is True
    )


def test_combine_labels_keeps_highest_sensitivity():
    public = LabeledValue.create(
        "public",
        sensitivity=Sensitivity.PUBLIC,
    )

    private = LabeledValue.create(
        "private",
        sensitivity=Sensitivity.USER_PRIVATE,
        categories={
            "user_secret",
        },
    )

    combined = combine_labels(
        public.label,
        private.label,
    )

    assert (
        combined.sensitivity
        == Sensitivity.USER_PRIVATE
    )

    assert (
        "user_secret"
        in combined.categories
    )
