from pathlib import Path


SOURCE = Path(
    "src/sophyane/enterprise/postgres.py"
).read_text(encoding="utf-8")


def test_enterprise_core_targets_v2():
    assert '"enterprise-core"' in SOURCE
    assert "CORE_VERSION = 2" in SOURCE


def test_v2_has_explicit_upgrade_path():
    assert "_upgrade_core_v1_to_v2" in SOURCE
    assert "_current_core_version" in SOURCE


def test_user_party_tenant_integrity_is_database_enforced():
    assert "UNIQUE (tenant_id, id)" in SOURCE
    assert "FOREIGN KEY (tenant_id, party_id)" in SOURCE
    assert "REFERENCES identity.parties (tenant_id, id)" in SOURCE


def test_user_role_tenant_integrity_is_database_enforced():
    assert "tenant_id UUID" in SOURCE
    assert "FOREIGN KEY (tenant_id, user_id)" in SOURCE
    assert "FOREIGN KEY (tenant_id, role_id)" in SOURCE


def test_audit_actor_tenant_integrity_is_database_enforced():
    assert "FOREIGN KEY (tenant_id, actor_party_id)" in SOURCE


def test_tenant_rls_uses_explicit_session_context():
    assert "ENABLE ROW LEVEL SECURITY" in SOURCE
    assert "FORCE ROW LEVEL SECURITY" in SOURCE
    assert "sophyane.tenant_id" in SOURCE
    assert "current_setting" in SOURCE


def test_global_permissions_are_not_rls_scoped():
    start = SOURCE.index(
        "iam.permissions ("
    )
    end = SOURCE.index(
        "iam.role_permissions (",
        start,
    )

    permissions_block = SOURCE[start:end]

    assert "ROW LEVEL SECURITY" not in permissions_block

def test_audit_append_only_contract_survives_v2():
    assert "audit.reject_event_mutation" in SOURCE
    assert "BEFORE UPDATE OR DELETE" in SOURCE
