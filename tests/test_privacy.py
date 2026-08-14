from __future__ import annotations

from pathlib import Path

from sophyane.privacy import (
    ZeroKnowledgePrivacyVault,
    sanitize_sensitive_text,
)


def test_generic_email_is_redacted() -> None:
    result = sanitize_sensitive_text(
        "contact person@example.com"
    )

    assert "person@example.com" not in result
    assert "<REDACTED_EMAIL>" in result


def test_generic_phone_is_redacted() -> None:
    result = sanitize_sensitive_text(
        "phone +15551234567"
    )

    assert "+15551234567" not in result
    assert "<REDACTED_PHONE>" in result


def test_generic_stripe_secret_is_redacted() -> None:
    secret = (
        "sk_live_"
        + "A" * 32
    )

    result = sanitize_sensitive_text(
        "token=" + secret
    )

    assert secret not in result


def test_generic_github_token_is_redacted() -> None:
    secret = (
        "ghp_"
        + "A" * 36
    )

    result = sanitize_sensitive_text(
        secret
    )

    assert secret not in result
    assert "<REDACTED_GITHUB_TOKEN>" in result


def test_environment_secret_has_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = ZeroKnowledgePrivacyVault(
        tmp_path
        / "secrets.env"
    )

    vault.secrets_path.write_text(
        'DEMO_SECRET="from-file"\n',
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "DEMO_SECRET",
        "from-env",
    )

    assert (
        vault.get_or_prompt_secret(
            "DEMO_SECRET"
        )
        == "from-env"
    )


def test_local_file_secret_fallback(
    tmp_path: Path,
) -> None:
    vault = ZeroKnowledgePrivacyVault(
        tmp_path
        / "secrets.env"
    )

    vault.secrets_path.write_text(
        'DEMO_SECRET="from-file"\n',
        encoding="utf-8",
    )

    assert (
        vault.get_or_prompt_secret(
            "DEMO_SECRET"
        )
        == "from-file"
    )


def test_source_contains_no_user_specific_literals() -> None:
    source = Path(
        "src/sophyane/privacy.py"
    ).read_text(
        encoding="utf-8",
    )

    forbidden_fragments = (
        "@gmail.com",
        "0321",
        "+923",
        "GB42",
        "aqel",
        "47EhKrcA",
    )

    lowered = source.casefold()

    for fragment in forbidden_fragments:
        assert (
            fragment.casefold()
            not in lowered
        )
