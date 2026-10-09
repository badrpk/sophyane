from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_retry_owner_survives_first_concurrent_serve_exit(
    monkeypatch,
):
    """
    Same-server concurrent serve_forever entries share retry authority.

    If the owning HTTP invocation returns while another invocation is
    still active, live retry must continue until the remaining HTTP
    lifetime also exits.
    """

    base_lock = threading.Lock()
    base_entries = 0

    first_base_entered = threading.Event()
    second_base_entered = threading.Event()

    release_first = threading.Event()
    release_second = threading.Event()

    retry_lock = threading.Lock()
    retry_calls = 0

    first_retry_seen = threading.Event()
    retry_after_first_exit = threading.Event()

    first_has_exited = threading.Event()

    def fake_base_serve_forever(
        self,
        *args,
        **kwargs,
    ):
        nonlocal base_entries

        with base_lock:
            base_entries += 1
            entry = base_entries

        if entry == 1:
            first_base_entered.set()
            assert release_first.wait(3.0)
            return

        if entry == 2:
            second_base_entered.set()
            assert release_second.wait(3.0)
            return

        raise AssertionError(
            f"Unexpected base serve_forever entry: {entry}"
        )

    def fake_retry():
        nonlocal retry_calls

        with retry_lock:
            retry_calls += 1

        first_retry_seen.set()

        if first_has_exited.is_set():
            retry_after_first_exit.set()

        return []

    monkeypatch.setattr(
        ThreadingHTTPServer,
        "serve_forever",
        fake_base_serve_forever,
    )
    monkeypatch.setattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        fake_retry,
    )

    server = portal.serve_portal(
        host="127.0.0.1",
        port=0,
    )

    first = threading.Thread(
        target=server.serve_forever,
        name="3k7o-first-serve",
        daemon=True,
    )

    second = threading.Thread(
        target=server.serve_forever,
        name="3k7o-second-serve",
        daemon=True,
    )

    try:
        first.start()

        assert first_base_entered.wait(1.0)
        assert first_retry_seen.wait(1.0)

        second.start()

        assert second_base_entered.wait(1.0)

        with retry_lock:
            calls_before_first_exit = retry_calls

        release_first.set()
        first.join(timeout=2.0)

        assert not first.is_alive()
        assert second.is_alive()

        first_has_exited.set()

        # Give the 100 ms retry cadence several opportunities.
        assert retry_after_first_exit.wait(0.5), (
            "Live retry stopped when the first/owning serve_forever "
            "invocation exited even though another same-server "
            "serve_forever invocation remained active."
        )

        with retry_lock:
            assert retry_calls > calls_before_first_exit

        assert server._whatsapp_retry_owner_active is True

    finally:
        release_first.set()
        release_second.set()

        first.join(timeout=2.0)

        if second.ident is not None:
            second.join(timeout=2.0)

        server.server_close()

    assert not first.is_alive()
    assert not second.is_alive()

    # Worker shutdown is asynchronous only if it was blocked inside retry.
    # This fake retry is non-blocking, so normal termination should settle.
    deadline = time.monotonic() + 1.0
    while (
        server._whatsapp_retry_owner_active
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)

    assert server._whatsapp_retry_owner_active is False
