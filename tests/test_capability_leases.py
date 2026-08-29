from sophyane.capability_leases import (
    CapabilityLeaseManager,
)


def test_lease_is_scope_and_capability_bound():
    now = [100.0]

    manager = CapabilityLeaseManager(
        clock=lambda: now[0]
    )

    lease = manager.issue(
        capability="browser_network",
        scope="task-123",
        ttl_seconds=10,
    )

    assert (
        manager.authorize(
            lease.lease_id,
            capability="browser_network",
            scope="task-123",
            consume=False,
        )
        is True
    )

    assert (
        manager.authorize(
            lease.lease_id,
            capability="browser_network",
            scope="other-task",
            consume=False,
        )
        is False
    )

    assert (
        manager.authorize(
            lease.lease_id,
            capability="local_filesystem",
            scope="task-123",
            consume=False,
        )
        is False
    )


def test_lease_expires():
    now = [10.0]

    manager = CapabilityLeaseManager(
        clock=lambda: now[0]
    )

    lease = manager.issue(
        capability="local_filesystem",
        scope="workspace-a",
        ttl_seconds=1,
    )

    now[0] = 12.0

    assert (
        manager.authorize(
            lease.lease_id,
            capability="local_filesystem",
            scope="workspace-a",
        )
        is False
    )


def test_single_use_lease_cannot_be_replayed():
    manager = CapabilityLeaseManager(
        clock=lambda: 10.0
    )

    lease = manager.issue(
        capability="local_filesystem",
        scope="workspace",
        max_uses=1,
    )

    assert (
        manager.authorize(
            lease.lease_id,
            capability="local_filesystem",
            scope="workspace",
        )
        is True
    )

    assert (
        manager.authorize(
            lease.lease_id,
            capability="local_filesystem",
            scope="workspace",
        )
        is False
    )


def test_revoked_lease_is_dead():
    manager = CapabilityLeaseManager(
        clock=lambda: 10.0
    )

    lease = manager.issue(
        capability="local_reasoning",
        scope="task",
    )

    manager.revoke(
        lease.lease_id
    )

    assert (
        manager.authorize(
            lease.lease_id,
            capability="local_reasoning",
            scope="task",
        )
        is False
    )
