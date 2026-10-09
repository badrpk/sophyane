from __future__ import annotations

import threading
import time

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_portal_app_construction_does_not_start_live_retry_owner(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        lambda: calls.append("retry") or [],
    )

    before = set(threading.enumerate())

    portal.PortalApp()

    time.sleep(0.05)

    after = set(threading.enumerate())

    assert calls == []
    assert after - before == set()


def test_running_portal_server_owns_live_retry_lifecycle(
    monkeypatch,
):
    """
    Contract:

    A constructed PortalApp is not the persistent retry owner.

    Once the HTTP server actually enters serve_forever(), exactly one
    live retry lifecycle must exist and invoke the existing messaging
    retry authority while that server remains alive.

    Stopping the server must stop that retry lifecycle as well.
    """

    retry_seen = threading.Event()
    retry_calls = []
    retry_lock = threading.Lock()

    def fake_retry():
        with retry_lock:
            retry_calls.append(time.monotonic())
        retry_seen.set()
        return []

    monkeypatch.setattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        fake_retry,
    )

    server = portal.serve_portal(
        host="127.0.0.1",
        port=0,
    )

    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    try:
        server_thread.start()

        assert retry_seen.wait(1.0), (
            "A running portal server has no live retry owner: "
            "_retry_whatsapp_inbound_spool() was never invoked."
        )

        with retry_lock:
            assert len(retry_calls) >= 1

    finally:
        server.shutdown()
        server.server_close()

        server_thread.join(timeout=1.0)

    assert not server_thread.is_alive()

    with retry_lock:
        calls_after_shutdown = len(retry_calls)

    time.sleep(0.15)

    with retry_lock:
        assert len(retry_calls) == calls_after_shutdown, (
            "Live retry activity continued after portal server "
            "termination."
        )
