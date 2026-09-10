import json

import pytest
import websocket

import sophyane.providers.nifdu_cdp_bridge as bridge


class _Page:
    @staticmethod
    def value():
        return {
            "webSocketDebuggerUrl":
            "ws://127.0.0.1/fake"
        }


class _Socket:
    def __init__(self, messages=None):
        self.messages = list(
            messages or []
        )
        self.timeouts = []
        self.sent = []
        self.closed = False

    def settimeout(self, value):
        self.timeouts.append(
            float(value)
        )

    def send(self, payload):
        self.sent.append(
            json.loads(payload)
        )

    def recv(self):
        if not self.messages:
            raise websocket.WebSocketTimeoutException(
                "synthetic recv timeout"
            )

        value = self.messages.pop(0)

        if isinstance(
            value,
            Exception,
        ):
            raise value

        return json.dumps(
            value
        )

    def close(self):
        self.closed = True


def test_cdp_connection_timeout_is_capped_by_bridge_timeout(
    monkeypatch,
):
    captured = {}
    sock = _Socket()

    def fake_create_connection(
        url,
        **kwargs,
    ):
        captured["url"] = url
        captured.update(kwargs)
        return sock

    monkeypatch.setattr(
        bridge.websocket,
        "create_connection",
        fake_create_connection,
    )

    monkeypatch.setattr(
        bridge,
        "TIMEOUT",
        3,
    )

    cdp = bridge.CDP(
        _Page.value()
    )

    assert captured["timeout"] <= 3.0

    cdp.close()


def test_cdp_recv_timeout_is_translated_to_bounded_timeout(
    monkeypatch,
):
    sock = _Socket(
        [
            websocket.WebSocketTimeoutException(
                "synthetic recv timeout"
            ),
        ]
    )

    monkeypatch.setattr(
        bridge.websocket,
        "create_connection",
        lambda *args, **kwargs: sock,
    )

    monkeypatch.setattr(
        bridge,
        "TIMEOUT",
        2,
    )

    cdp = bridge.CDP(
        _Page.value()
    )

    with pytest.raises(
        TimeoutError,
        match="CDP Runtime.enable",
    ):
        cdp.call(
            "Runtime.enable"
        )

    assert sock.timeouts

    assert max(
        sock.timeouts
    ) <= 2.0


def test_unrelated_cdp_events_do_not_reset_absolute_deadline(
    monkeypatch,
):
    sock = _Socket(
        [
            {
                "method": "Network.requestWillBeSent",
                "params": {},
            },
            {
                "method": "Page.lifecycleEvent",
                "params": {},
            },
            {
                "id": 1,
                "result": {
                    "too_late": True,
                },
            },
        ]
    )

    monkeypatch.setattr(
        bridge.websocket,
        "create_connection",
        lambda *args, **kwargs: sock,
    )

    monkeypatch.setattr(
        bridge,
        "TIMEOUT",
        1,
    )

    ticks = iter(
        [
            # call deadline creation
            0.0,

            # before first recv
            0.2,

            # after unrelated event
            0.7,

            # after second unrelated event:
            # operation deadline has expired.
            1.01,
        ]
    )

    monkeypatch.setattr(
        bridge.time,
        "monotonic",
        lambda: next(ticks),
    )

    cdp = bridge.CDP(
        _Page.value()
    )

    with pytest.raises(
        TimeoutError,
        match="CDP Runtime.evaluate",
    ):
        cdp.call(
            "Runtime.evaluate"
        )

    # The matching response existed in the synthetic stream,
    # but it must never be consumed after the absolute deadline.
    assert len(
        sock.messages
    ) == 1


def test_chat_page_has_one_bounded_readiness_selection_window():
    import inspect

    source = inspect.getsource(
        bridge.chat_page
    )

    assert (
        "selection_deadline"
        in source
    )

    assert (
        "CDP_READINESS_TIMEOUT"
        in source
    )

    deadline_check = source.index(
        "time.monotonic()"
    )

    selection_ref = source.index(
        "selection_deadline",
        deadline_check,
    )

    break_ref = source.index(
        "break",
        selection_ref,
    )

    assert deadline_check < selection_ref < break_ref
