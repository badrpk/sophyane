from sophyane.capability_chain_guard import (
    CapabilityChainGuard,
    ChainRequest,
)
from sophyane.capability_flow_graph import (
    default_capability_graph,
)
from sophyane.capability_flow_policy import (
    LabeledValue,
    Sensitivity,
)


def test_chain_requires_complete_verifier_set():
    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    value = LabeledValue.create(
        "public query"
    )

    request = ChainRequest(
        capabilities=(
            "local_reasoning",
            "browser_network",
        ),
        scope="task",
        verifier_evidence=frozenset(),
    )

    result = guard.evaluate(
        request=request,
        value=value,
    )

    assert result.allowed is False

    assert (
        "schema"
        in result.missing_verifiers
    )

    assert (
        "network_policy"
        in result.missing_verifiers
    )


def test_fully_verified_public_chain_can_receive_leases():
    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    value = LabeledValue.create(
        "public query"
    )

    request = ChainRequest(
        capabilities=(
            "local_reasoning",
            "browser_network",
        ),
        scope="task-1",
        verifier_evidence=frozenset(
            {
                "schema",
                "network_policy",
            }
        ),
    )

    admission = guard.evaluate(
        request=request,
        value=value,
    )

    assert admission.allowed is True

    leases = guard.issue_leases(
        request=request,
        value=value,
    )

    assert len(leases) == 2


def test_verifiers_cannot_override_secret_flow_policy():
    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    secret = LabeledValue.create(
        "secret",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "credential",
        },
    )

    request = ChainRequest(
        capabilities=(
            "local_reasoning",
            "browser_network",
            "image_render",
            "ocr_decode",
        ),
        scope="task",
        verifier_evidence=frozenset(
            {
                "schema",
                "network_policy",
                "information_flow",
                "provenance",
            }
        ),
    )

    result = guard.evaluate(
        request=request,
        value=secret,
    )

    assert result.allowed is False


def test_nifdu_style_recommendation_has_no_authority():
    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    secret = LabeledValue.create(
        "cookie",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "cookie",
            "authentication",
        },
    )

    #
    # Imagine an external supervisor recommended this exact sequence.
    # Recommendation does not bypass the local policy.
    #
    recommendation = ChainRequest(
        capabilities=(
            "local_reasoning",
            "browser_network",
            "image_render",
            "ocr_decode",
            "agentic_memory",
        ),
        scope="nifdu-proposed-chain",
        verifier_evidence=frozenset(
            {
                "schema",
                "network_policy",
                "information_flow",
                "provenance",
                "memory_evidence",
            }
        ),
    )

    result = guard.evaluate(
        request=recommendation,
        value=secret,
    )

    assert result.allowed is False

    assert (
        guard.issue_leases(
            request=recommendation,
            value=secret,
        )
        == ()
    )


def test_local_secret_reasoning_allowed_but_external_transition_denied():
    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    secret = LabeledValue.create(
        "private-credential",
        sensitivity=Sensitivity.AUTH_SECRET,
        categories={
            "credential",
        },
        origin="secure-local-state",
    )

    local_request = ChainRequest(
        capabilities=(
            "local_reasoning",
        ),
        scope="local-secret-analysis",
        verifier_evidence=frozenset(
            {
                "schema",
            }
        ),
    )

    local_result = guard.evaluate(
        request=local_request,
        value=secret,
    )

    assert local_result.allowed is True

    external_request = ChainRequest(
        capabilities=(
            "local_reasoning",
            "browser_network",
        ),
        scope="external-secret-attempt",
        verifier_evidence=frozenset(
            {
                "schema",
                "network_policy",
            }
        ),
    )

    external_result = guard.evaluate(
        request=external_request,
        value=secret,
    )

    assert external_result.allowed is False

    assert (
        "browser_network"
        in external_result.reason
    )

    assert (
        guard.issue_leases(
            request=external_request,
            value=secret,
        )
        == ()
    )
