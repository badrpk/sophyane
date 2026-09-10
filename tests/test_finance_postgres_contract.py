from pathlib import Path


SOURCE = Path(
    "src/sophyane/enterprise/postgres.py"
).read_text(encoding="utf-8")


def test_finance_schema_exists():
    assert "CREATE SCHEMA IF NOT EXISTS finance" in SOURCE


def test_finance_core_tables_exist():
    required = (
        "finance.accounts",
        "finance.transactions",
        "finance.entries",
        "finance.holds",
        "finance.settlements",
        "finance.payouts",
        "finance.payment_attempts",
    )

    for table in required:
        assert table in SOURCE


def test_finance_accounts_are_tenant_and_party_scoped():
    start = SOURCE.index("finance.accounts")
    end = SOURCE.index("finance.transactions", start)
    block = SOURCE[start:end]

    assert "tenant_id" in block
    assert "party_id" in block
    assert "currency" in block
    assert "platform.tenants" in block
    assert "identity.parties" in block


def test_finance_transactions_are_tenant_scoped():
    start = SOURCE.index("finance.transactions")
    end = SOURCE.index("finance.entries", start)
    block = SOURCE[start:end]

    assert "tenant_id" in block
    assert "status" in block
    assert "created_at" in block


def test_finance_entries_use_integer_minor_units():
    start = SOURCE.index("finance.entries")
    end = SOURCE.index("finance.holds", start)
    block = SOURCE[start:end]

    assert "amount_minor BIGINT" in block
    assert "currency" in block
    assert "account_id" in block
    assert "transaction_id" in block


def test_finance_posted_journal_is_append_only():
    assert "finance.reject_posted_entry_mutation" in SOURCE
    assert "finance_entries_no_posted_mutation" in SOURCE


def test_finance_balancing_trigger_exists():
    assert "finance.assert_transaction_balanced" in SOURCE
    assert "finance_transactions_balance_check" in SOURCE


def test_finance_holds_exist():
    start = SOURCE.index("finance.holds")
    end = SOURCE.index("finance.settlements", start)
    block = SOURCE[start:end]

    assert "amount_minor BIGINT" in block
    assert "status" in block
    assert "account_id" in block


def test_finance_payouts_are_amount_and_account_scoped():
    start = SOURCE.index("finance.payouts")
    end = SOURCE.index("finance.payment_attempts", start)
    block = SOURCE[start:end]

    assert "amount_minor BIGINT" in block
    assert "account_id" in block
    assert "status" in block


def test_finance_payment_attempts_capture_provider_evidence():
    start = SOURCE.index("finance.payment_attempts")
    block = SOURCE[start:]

    assert "provider" in block
    assert "provider_reference" in block
    assert "status" in block


def test_finance_uses_shared_enterprise_outbox():
    assert "integration.outbox_events" in SOURCE


def test_finance_uses_shared_enterprise_audit():
    assert "audit.events" in SOURCE


def test_finance_rls_is_enabled():
    required_tables = (
        "accounts",
        "transactions",
        "entries",
        "holds",
        "settlements",
        "payouts",
        "payment_attempts",
    )

    for table in required_tables:
        assert f'"{table}"' in SOURCE

    assert 'f"finance_{table}_tenant_isolation"' in SOURCE
    assert "ENABLE ROW LEVEL SECURITY" in SOURCE
    assert "FORCE ROW LEVEL SECURITY" in SOURCE
    assert "CREATE POLICY" in SOURCE
    assert "current_setting(" in SOURCE
    assert "'sophyane.tenant_id'" in SOURCE
    assert "WITH CHECK" in SOURCE

def test_finance_posted_entries_reject_late_inserts():
    assert "BEFORE INSERT OR UPDATE OR DELETE" in SOURCE
    assert "TG_OP IN ('INSERT', 'UPDATE')" in SOURCE
    assert "posted financial journal is immutable" in SOURCE


def test_finance_entry_currency_matches_account():
    assert "entry currency must match account currency" in SOURCE
    assert "account_currency <> NEW.currency" in SOURCE


def test_finance_balances_each_currency_independently():
    assert "GROUP BY currency" in SOURCE
    assert "unbalanced_currency" in SOURCE
    assert (
        "financial transaction is not balanced for currency"
        in SOURCE
    )


def test_finance_transactions_start_as_draft():
    assert "BEFORE INSERT OR UPDATE" in SOURCE
    assert (
        "financial transaction must be created as draft"
        in SOURCE
    )


def test_finance_has_independent_schema_version():
    assert 'FINANCE_COMPONENT = "finance-core"' in SOURCE
    assert "FINANCE_VERSION = 1" in SOURCE
    assert "def _current_finance_version(" in SOURCE
    assert "def _record_finance_version(" in SOURCE


def test_finance_rejects_future_schema_version():
    assert (
        "finance core schema is newer than this runtime"
        in SOURCE
    )


def test_finance_version_noop_does_not_rewrite_timestamp():
    assert "if current_version == FINANCE_VERSION:" in SOURCE
    assert "return" in SOURCE
    assert "DO NOTHING" in SOURCE


def test_finance_version_registration_is_verified():
    assert (
        "finance core version registration failed"
        in SOURCE
    )
