import ast
from pathlib import Path


RAILS = Path("src/sophyane/cloud/payments_rails.py")
CRYPTO = Path("src/sophyane/cloud/crypto_billing.py")
STRIPE = Path("src/sophyane/cloud/stripe_billing.py")


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            lines = source.splitlines()
            return "\n".join(
                lines[node.lineno - 1 : node.end_lineno]
            )

    raise AssertionError(f"{name!r} missing from {path}")


def test_payment_rails_user_proof_cannot_self_certify():
    body = _function_source(RAILS, "user_report_payment")

    assert "SOPHYANE_VERIFIED_PAYMENT_AUTHORITY_V1" in body
    assert "mark_paid(" not in body
    assert "awaiting_confirm" in body


def test_crypto_user_txid_cannot_self_certify():
    body = _function_source(CRYPTO, "user_report_payment")

    assert "SOPHYANE_VERIFIED_CRYPTO_PAYMENT_AUTHORITY_V1" in body
    assert "mark_paid(" not in body
    assert "try_auto_confirm_monero" in body
    assert "awaiting_confirm" in body


def test_monero_confirmation_uses_independent_rpc_path():
    body = _function_source(CRYPTO, "try_auto_confirm_monero")
    low = body.lower()

    assert "get_transfers" in low
    assert "mark_paid" in body


def test_stripe_confirmation_requires_remote_state():
    body = _function_source(STRIPE, "confirm_session")
    low = body.lower()

    assert "retrieve" in low
    assert (
        "payment_status" in low
        or "status" in low
    )
    assert (
        '"paid"' in low
        or "'paid'" in low
        or '"complete"' in low
        or "'complete'" in low
    )


if __name__ == "__main__":
    raise SystemExit("run with pytest")
