from __future__ import annotations

import hashlib
import hmac

import sophyane.cloud.messaging as messaging


def test_verify_token_is_loaded_from_messaging_env(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / "messaging.env"
    env_file.write_text(
        "WHATSAPP_VERIFY_TOKEN=file-verify-secret\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )

    monkeypatch.delenv(
        "WHATSAPP_VERIFY_TOKEN",
        raising=False,
    )

    path = (
        "/api/v1/messaging/whatsapp/webhook"
        "?hub.mode=subscribe"
        "&hub.verify_token=file-verify-secret"
        "&hub.challenge=123456"
    )

    assert (
        messaging.verify_whatsapp_webhook_request(path)
        == "123456"
    )


def test_app_secret_is_loaded_from_messaging_env(
    monkeypatch,
    tmp_path,
):
    secret = "file-app-secret"

    env_file = tmp_path / "messaging.env"
    env_file.write_text(
        f"WHATSAPP_APP_SECRET={secret}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )

    monkeypatch.delenv(
        "WHATSAPP_APP_SECRET",
        raising=False,
    )

    raw = b'{"object":"whatsapp_business_account"}'

    digest = hmac.new(
        secret.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()

    signature = f"sha256={digest}"

    assert messaging.verify_whatsapp_webhook_signature(
        raw,
        signature,
    ) is True


def test_wrong_signature_is_rejected_with_env_file_secret(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / "messaging.env"
    env_file.write_text(
        "WHATSAPP_APP_SECRET=file-app-secret\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )

    monkeypatch.delenv(
        "WHATSAPP_APP_SECRET",
        raising=False,
    )

    assert messaging.verify_whatsapp_webhook_signature(
        b'{"object":"whatsapp_business_account"}',
        "sha256=" + ("0" * 64),
    ) is False
