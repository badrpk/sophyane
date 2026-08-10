import urllib.error

import sophyane.local_server as server


class _Response:
    def __init__(
        self,
        status: int,
        body: bytes,
    ) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        return None


def test_wait_until_ready_rejects_http_503(
    monkeypatch,
) -> None:
    calls = 0

    def fake_urlopen(
        request,
        timeout,
    ):
        nonlocal calls
        calls += 1

        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "loading",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    monkeypatch.setattr(
        server.time,
        "sleep",
        lambda _value: None,
    )

    times = iter(
        (
            0.0,
            0.0,
            2.0,
        )
    )

    monkeypatch.setattr(
        server.time,
        "monotonic",
        lambda: next(
            times,
            2.0,
        ),
    )

    assert (
        server.wait_until_ready(
            timeout=1.0
        )
        is False
    )

    assert calls >= 1


def test_wait_until_ready_requires_status_ok(
    monkeypatch,
) -> None:
    responses = iter(
        (
            _Response(
                200,
                b'{"status":"loading"}',
            ),
            _Response(
                200,
                b'{"status":"ok"}',
            ),
        )
    )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout:
            next(responses),
    )

    monkeypatch.setattr(
        server.time,
        "sleep",
        lambda _value: None,
    )

    monkeypatch.setattr(
        server.time,
        "monotonic",
        lambda: 0.0,
    )

    assert server.wait_until_ready(
        timeout=5.0
    )
