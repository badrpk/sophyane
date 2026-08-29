from sophyane.capability_flow_graph import (
    default_capability_graph,
)
from sophyane.capability_flow_policy import (
    LabeledValue,
    Sensitivity,
)


def test_normal_public_browser_chain_allowed():
    graph = default_capability_graph()

    value = LabeledValue.create(
        "public query",
        sensitivity=Sensitivity.PUBLIC,
    )

    result = graph.validate_chain(
        (
            "local_reasoning",
            "browser_network",
            "image_render",
            "ocr_decode",
            "agentic_memory",
        ),
        value,
    )

    assert result.allowed is True


def test_credential_exfiltration_chain_is_blocked():
    graph = default_capability_graph()

    value = LabeledValue.create(
        "session-secret",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "credential",
            "session_token",
        },
        origin="credential-store",
    )

    #
    # Secret material may be inspected by the local-only reasoning stage.
    #
    local_only = graph.validate_chain(
        (
            "local_reasoning",
        ),
        value,
    )

    assert local_only.allowed is True

    #
    # The same tainted value must fail as soon as the chain reaches its
    # first external/network sink.
    #
    result = graph.validate_chain(
        (
            "local_reasoning",
            "browser_network",
            "image_render",
            "ocr_decode",
            "agentic_memory",
        ),
        value,
    )

    assert result.allowed is False

    assert (
        "browser_network"
        in result.reason
    )

    assert (
        "external"
        in result.reason
        or "sensitivity"
        in result.reason
        or "sensitive"
        in result.reason
    )


def test_private_value_cannot_be_laundered_through_rendering():
    graph = default_capability_graph()

    value = LabeledValue.create(
        {
            "email":
                "private@example.invalid",
        },
        sensitivity=Sensitivity.USER_PRIVATE,
        categories={
            "user_secret",
        },
        origin="user-input",
    )

    rendered = value.transformed(
        "encoded-html",
        capability="local_reasoning",
        operation="encode",
    )

    result = graph.validate_chain(
        (
            "local_reasoning",
            "browser_network",
            "image_render",
        ),
        rendered,
    )

    assert result.allowed is False


def test_undeclared_capability_transition_is_rejected():
    graph = default_capability_graph()

    value = LabeledValue.create(
        "hello"
    )

    result = graph.validate_chain(
        (
            "local_filesystem",
            "browser_network",
        ),
        value,
    )

    assert result.allowed is False

    assert (
        "undeclared capability transition"
        in result.reason
    )


def test_secret_transformation_does_not_lower_sensitivity_before_external_sink():
    graph = default_capability_graph()

    original = LabeledValue.create(
        "credential-secret",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "credential",
            "authentication",
        },
        origin="local-secret-store",
    )

    encoded = original.transformed(
        "<html>opaque encoded representation</html>",
        capability="local_reasoning",
        operation="encode",
    )

    assert (
        encoded.label.sensitivity
        == Sensitivity.AUTH_SECRET
    )

    assert (
        "credential"
        in encoded.label.categories
    )

    assert (
        "local-secret-store"
        in encoded.label.origin_ids
    )

    result = graph.validate_chain(
        (
            "local_reasoning",
            "browser_network",
            "image_render",
            "ocr_decode",
            "agentic_memory",
        ),
        encoded,
    )

    assert result.allowed is False

    assert (
        "browser_network"
        in result.reason
    )
