from __future__ import annotations

from sophyane.cloud import messaging


def test_telegram_get_me_returns_bot_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        messaging,
        "_tg_api",
        lambda method: {
            "ok": True,
            "result": {
                "id": 123,
                "username": "test_bot",
            },
        },
    )

    result = messaging.telegram_get_me()

    assert result == {
        "ok": True,
        "bot": {
            "id": 123,
            "username": "test_bot",
        },
    }


def test_telegram_get_me_returns_api_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        messaging,
        "_tg_api",
        lambda method: {
            "ok": False,
            "description": "unauthorized",
        },
    )

    result = messaging.telegram_get_me()

    assert result["ok"] is False
    assert result["error"]["description"] == "unauthorized"


def test_telegram_get_me_returns_exception_message(
    monkeypatch,
) -> None:
    def broken_api(method):
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr(
        messaging,
        "_tg_api",
        broken_api,
    )

    result = messaging.telegram_get_me()

    assert result == {
        "ok": False,
        "error": "telegram unavailable",
    }
