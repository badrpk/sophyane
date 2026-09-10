from pathlib import Path


SOURCE = Path(
    "src/sophyane/enterprise/postgres.py"
).read_text(encoding="utf-8")


def test_tenant_transaction_is_context_manager():
    assert "@contextmanager" in SOURCE
    assert "def tenant_transaction(" in SOURCE


def test_tenant_id_is_validated_as_uuid():
    assert "UUID(str(tenant_id))" in SOURCE


def test_tenant_context_is_transaction_local():
    assert "sophyane.tenant_id" in SOURCE
    assert "set_config(" in SOURCE
    assert "true" in SOURCE.lower()


def test_tenant_transaction_uses_normal_connection_transaction():
    start = SOURCE.index(
        "def tenant_transaction("
    )
    end = SOURCE.index(
        "\n    def ",
        start + 1,
    )

    block = SOURCE[start:end]

    assert "with self.connect() as connection:" in block
    assert "with connection.cursor() as cursor:" in block
    assert "yield cursor" in block
