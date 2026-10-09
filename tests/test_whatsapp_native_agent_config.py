from __future__ import annotations

import stat

import sophyane.cloud.messaging as messaging


def _write_env(tmp_path, content: str):
    path = tmp_path / "messaging.env"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_native_agent_key_loaded_from_messaging_env(
    tmp_path,
    monkeypatch,
):
    env_file = _write_env(
        tmp_path,
        "WHATSAPP_AGENT_API_KEY=test-native-agent-key\n",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )
    monkeypatch.delenv(
        "WHATSAPP_AGENT_API_KEY",
        raising=False,
    )

    env = messaging.load_messaging_env()

    assert (
        env["WHATSAPP_AGENT_API_KEY"]
        == "test-native-agent-key"
    )


def test_native_agent_key_marks_whatsapp_enabled(
    tmp_path,
    monkeypatch,
):
    env_file = _write_env(
        tmp_path,
        "WHATSAPP_AGENT_API_KEY=test-native-agent-key\n",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )
    monkeypatch.delenv(
        "WHATSAPP_AGENT_API_KEY",
        raising=False,
    )

    wa = messaging.public_status()["channels"]["whatsapp"]

    assert wa["enabled"] is True
    assert wa["mode"] == "native_agent"
    assert wa["status"] == "needs_transport"


def test_native_agent_key_is_not_exposed_by_public_status(
    tmp_path,
    monkeypatch,
):
    secret = "super-secret-native-agent-key"

    env_file = _write_env(
        tmp_path,
        f"WHATSAPP_AGENT_API_KEY={secret}\n",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )
    monkeypatch.delenv(
        "WHATSAPP_AGENT_API_KEY",
        raising=False,
    )

    wa = messaging.public_status()["channels"]["whatsapp"]

    assert secret not in repr(wa)


def test_native_agent_config_does_not_masquerade_as_cloud_api(
    tmp_path,
    monkeypatch,
):
    env_file = _write_env(
        tmp_path,
        "WHATSAPP_AGENT_API_KEY=test-native-agent-key\n",
    )

    monkeypatch.setattr(
        messaging,
        "MESSAGING_ENV",
        env_file,
    )

    for name in (
        "WHATSAPP_AGENT_API_KEY",
        "WHATSAPP_CLOUD_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    wa = messaging.public_status()["channels"]["whatsapp"]

    assert wa["mode"] != "cloud_api"


def test_fixture_env_is_private(
    tmp_path,
):
    env_file = _write_env(
        tmp_path,
        "WHATSAPP_AGENT_API_KEY=test-native-agent-key\n",
    )

    mode = stat.S_IMODE(env_file.stat().st_mode)

    assert mode == 0o600
