def test_registered_peer_is_callable(
    tmp_path,
):
    from sophyane.peer_capability_adapter import (
        PeerCapabilityRegistry,
        PeerCapabilityRequest,
        PeerCapabilityResult,
    )

    registry = (
        PeerCapabilityRegistry()
    )

    def invoke(
        capability,
        objective,
        workspace,
    ):
        return PeerCapabilityResult(
            handled=True,
            ok=True,
            repository="xerus",
            capability=capability,
            output="memory result",
            evidence={
                "executed_repository": (
                    "xerus"
                ),
                "objective": objective,
            },
        )

    registry.register(
        repository="xerus",
        capabilities=(
            "persistent-memory",
            "retrieval",
        ),
        invoker=invoke,
    )

    result = registry.invoke(
        PeerCapabilityRequest(
            repository="xerus",
            capability="retrieval",
            objective="find prior memory",
            workspace=str(tmp_path),
        )
    )

    assert result.handled is True
    assert result.ok is True

    assert (
        result.evidence[
            "executed_repository"
        ]
        == "xerus"
    )


def test_unregistered_remote_peer_is_not_executed(
    tmp_path,
):
    from sophyane.peer_capability_adapter import (
        PeerCapabilityRegistry,
        PeerCapabilityRequest,
    )

    registry = (
        PeerCapabilityRegistry()
    )

    result = registry.invoke(
        PeerCapabilityRequest(
            repository="neuron",
            capability="learning",
            objective="learn",
            workspace=str(tmp_path),
        )
    )

    assert result.handled is False
    assert result.ok is False

    assert (
        result.evidence[
            "reason"
        ]
        == "PEER_ADAPTER_UNAVAILABLE"
    )
