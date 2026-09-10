from pathlib import Path


SOURCE = Path(
    "src/sophyane/multiagent_postgres.py"
).read_text(
    encoding="utf-8"
)


def test_reuses_enterprise_postgres():
    assert (
        "from sophyane.enterprise.postgres import"
        in SOURCE
    )
    assert "EnterprisePostgres" in SOURCE


def test_postgres_is_authoritative_coordination_plane():
    for table in (
        "agent_runtime.agents",
        "agent_runtime.tasks",
        "agent_runtime.messages",
        "agent_runtime.events",
    ):
        assert table in SOURCE


def test_atomic_task_claim_uses_skip_locked():
    assert "FOR UPDATE SKIP LOCKED" in SOURCE
    assert "lease_owner" in SOURCE
    assert "lease_expires_at" in SOURCE


def test_task_queue_has_retry_and_lease_recovery():
    assert "max_attempts" in SOURCE
    assert "requeue_expired_leases" in SOURCE
    assert "worker lease expired" in SOURCE


def test_agent_heartbeats_are_durable():
    assert "heartbeat_at TIMESTAMPTZ" in SOURCE
    assert "def heartbeat(" in SOURCE


def test_messages_are_claimed_atomically():
    start = SOURCE.index(
        "def claim_messages("
    )
    block = SOURCE[
        start:
        SOURCE.index(
            "def consume_message(",
            start,
        )
    ]

    assert "FOR UPDATE SKIP LOCKED" in block
    assert "claimed_by" in block


def test_message_and_task_idempotency_are_supported():
    assert SOURCE.count(
        "idempotency_key TEXT UNIQUE"
    ) >= 2


def test_tables_remain_authoritative_not_notify():
    assert "LISTEN/NOTIFY may be added" in SOURCE

    # Documentation may mention LISTEN/NOTIFY. The V1 implementation must
    # not execute either PostgreSQL command; durable tables are authoritative.
    executable_sql = SOURCE.replace(
        "LISTEN/NOTIFY may be added",
        "notification wakeups may be added",
    )

    assert "LISTEN " not in executable_sql
    assert "NOTIFY " not in executable_sql


def test_agent_state_control_exists():
    for name in (
        "register_agent",
        "heartbeat",
        "set_agent_state",
        "list_agents",
    ):
        assert f"def {name}(" in SOURCE


def test_task_lifecycle_control_exists():
    for name in (
        "enqueue_task",
        "claim_task",
        "renew_lease",
        "complete_task",
        "fail_task",
        "requeue_expired_leases",
    ):
        assert f"def {name}(" in SOURCE
