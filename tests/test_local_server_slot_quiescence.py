from __future__ import annotations

import io
import json

import sophyane.local_server as local_server


class _Response:
    def __init__(
        self,
        payload,
    ):
        self._payload = payload

    def __enter__(
        self,
    ):
        return self

    def __exit__(
        self,
        *_args,
    ):
        return False

    def read(
        self,
    ):
        return json.dumps(
            self._payload
        ).encode(
            "utf-8"
        )


def test_wait_until_idle_observes_async_slot_release(
    monkeypatch,
) -> None:
    states = iter(
        (
            [
                {
                    "id": 0,
                    "is_processing": True,
                }
            ],
            [
                {
                    "id": 0,
                    "is_processing": True,
                }
            ],
            [
                {
                    "id": 0,
                    "is_processing": False,
                }
            ],
        )
    )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs:
            _Response(
                next(
                    states
                )
            ),
    )

    monkeypatch.setattr(
        local_server.time,
        "sleep",
        lambda _seconds:
            None,
    )

    assert (
        local_server.wait_until_idle(
            timeout=2.0,
            poll_interval=0.01,
        )
        is True
    )


def test_wait_until_idle_accepts_single_clean_slot(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs:
            _Response(
                [
                    {
                        "id": 0,
                        "is_processing": False,
                    }
                ]
            ),
    )

    assert (
        local_server.wait_until_idle(
            timeout=1.0,
        )
        is True
    )
