from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_retry_failure_does_not_kill_live_retry_owner(
    monkeypatch,
):
    """
    A transient exception from the durable retry authority must not kill
    the server-owned retry lifecycle.
    """

    base_entered = threading.Event()
    release_base = threading.Event()
    recovered = threading.Event()

    call_lock = threading.Lock()
    call_count = 0

    def fake_base_serve_forever(
        self,
        *args,
        **kwargs,
    ):
        base_entered.set()
        assert release_base.wait(2.0)

    def flaky_retry():
        nonlocal call_count

        with call_lock:
            call_count += 1
            current = call_count

        if current == 1:
            raise RuntimeError("synthetic retry failure")

        recovered.set()
        return []

    monkeypatch.setattr(
        ThreadingHTTPServer,
        "serve_forever",
        fake_base_serve_forever,
    )
    monkeypatch.setattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        flaky_retry,
    )

    server = portal.serve_portal(
        host="127.0.0.1",
        port=0,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    try:
        thread.start()

        assert base_entered.wait(1.0)
        assert recovered.wait(1.0), (
            "The live retry owner died after one retry exception."
        )

        with call_lock:
            assert call_count >= 2
    finally:
        release_base.set()
        thread.join(timeout=2.0)
        server.server_close()

    assert not thread.is_alive()


def test_same_server_cannot_create_two_live_retry_owners(
    monkeypatch,
):
    """
    Exactly one live retry owner may exist for one portal server object.

    Concurrent/reentrant serve_forever() entry must not create a second
    WhatsApp retry worker.
    """

    release_base = threading.Event()

    base_lock = threading.Lock()
    base_entries = 0
    both_base_entries = threading.Event()

    retry_lock = threading.Lock()
    retry_thread_ids: set[int] = set()
    retry_observed = threading.Event()

    def fake_base_serve_forever(
        self,
        *args,
        **kwargs,
    ):
        nonlocal base_entries

        with base_lock:
            base_entries += 1
            if base_entries >= 2:
                both_base_entries.set()

        assert release_base.wait(2.0)

    def fake_retry():
        with retry_lock:
            retry_thread_ids.add(
                threading.get_ident()
            )
        retry_observed.set()
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
        name="3k7h-first-server-entry",
        daemon=True,
    )
    second = threading.Thread(
        target=server.serve_forever,
        name="3k7h-second-server-entry",
        daemon=True,
    )

    try:
        first.start()

        assert retry_observed.wait(1.0), (
            "First server lifetime did not establish retry ownership."
        )

        second.start()

        assert both_base_entries.wait(1.0), (
            "Controlled base serve_forever did not receive "
            "both concurrent entries."
        )

        # Current retry cadence is 0.1 s. Give both potential workers
        # enough time to identify themselves deterministically.
        deadline = time.monotonic() + 0.5

        while time.monotonic() < deadline:
            with retry_lock:
                if len(retry_thread_ids) >= 2:
                    break
            time.sleep(0.01)

        with retry_lock:
            owners = set(retry_thread_ids)

        assert len(owners) == 1, (
            "One portal server object created multiple concurrent "
            f"live retry owners: {owners}"
        )
    finally:
        release_base.set()

        first.join(timeout=2.0)
        second.join(timeout=2.0)

        server.server_close()

    assert not first.is_alive()
    assert not second.is_alive()
