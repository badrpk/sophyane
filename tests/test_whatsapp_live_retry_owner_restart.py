from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_same_server_reacquires_retry_owner_after_owner_exit(
    monkeypatch,
):
    """
    One server object may have multiple sequential serve_forever lifetimes.

    When the first owning lifetime exits:
    - its retry worker must stop,
    - ownership must be released,
    - a later lifetime must acquire a fresh retry owner.
    """

    base_lock = threading.Lock()
    base_entries = 0

    first_base_entered = threading.Event()
    second_base_entered = threading.Event()

    release_first = threading.Event()
    release_second = threading.Event()

    retry_lock = threading.Lock()
    retry_owner_threads: set[threading.Thread] = set()
    first_retry_seen = threading.Event()
    second_retry_seen = threading.Event()

    first_owner_thread: threading.Thread | None = None

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
            assert release_first.wait(2.0)
            return

        if entry == 2:
            second_base_entered.set()
            assert release_second.wait(2.0)
            return

        raise AssertionError(
            f"Unexpected base serve_forever entry: {entry}"
        )

    def fake_retry():
        nonlocal first_owner_thread

        owner_thread = threading.current_thread()

        with retry_lock:
            retry_owner_threads.add(owner_thread)

            if first_owner_thread is None:
                first_owner_thread = owner_thread
                first_retry_seen.set()
            elif owner_thread is not first_owner_thread:
                second_retry_seen.set()

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
        name="3k7j-first-lifetime",
        daemon=True,
    )

    second = threading.Thread(
        target=server.serve_forever,
        name="3k7j-second-lifetime",
        daemon=True,
    )

    try:
        first.start()

        assert first_base_entered.wait(1.0)
        assert first_retry_seen.wait(1.0)

        release_first.set()
        first.join(timeout=2.0)

        assert not first.is_alive()
        assert server._whatsapp_retry_owner_active is False

        second.start()

        assert second_base_entered.wait(1.0)

        assert second_retry_seen.wait(1.0), (
            "The same server object did not establish a fresh "
            "retry owner after the first owner exited."
        )

        with retry_lock:
            owners = set(retry_owner_threads)

        assert len(owners) == 2, (
            "Expected distinct retry worker objects across "
            f"sequential server lifetimes; observed {owners}"
        )
    finally:
        release_first.set()
        release_second.set()

        first.join(timeout=2.0)
        second.join(timeout=2.0)

        server.server_close()

    assert not first.is_alive()
    assert not second.is_alive()
    assert server._whatsapp_retry_owner_active is False
