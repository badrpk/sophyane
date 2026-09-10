from pathlib import Path


SOURCE = Path(
    "src/sophyane/enterprise/postgres.py"
).read_text(encoding="utf-8")


def test_reuses_canonical_postgres_dsn():
    assert "SOPHYANE_POSTGRES_DSN" in SOURCE
    assert "dbname=sophyane" in SOURCE
    assert "connect_timeout=3" in SOURCE


def test_core_enterprise_schemas_are_declared():
    for schema in (
        "platform",
        "identity",
        "iam",
        "audit",
        "integration",
    ):
        assert f'"{schema}"' in SOURCE


def test_enterprise_time_is_timezone_aware():
    assert "TIMESTAMPTZ" in SOURCE
    assert "TIMESTAMP DEFAULT" not in SOURCE


def test_enterprise_ids_are_database_generated():
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in SOURCE
    assert "DEFAULT gen_random_uuid()" in SOURCE


def test_audit_is_append_only():
    assert "audit.reject_event_mutation" in SOURCE
    assert "BEFORE UPDATE OR DELETE" in SOURCE


def test_idempotency_is_tenant_scoped():
    assert "integration.idempotency_keys" in SOURCE
    assert "PRIMARY KEY (" in SOURCE
    assert "tenant_id" in SOURCE
    assert "scope" in SOURCE


def test_transactional_outbox_exists():
    assert "integration.outbox_events" in SOURCE
    assert "published_at" in SOURCE
    assert "outbox_unpublished_idx" in SOURCE
