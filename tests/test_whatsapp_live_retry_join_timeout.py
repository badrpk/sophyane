from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_owner_not_released_while_retry_worker_survives_join(
    monkeypatch,
):
    """
    Retry ownership must describe the actual retry worker lifetime.

    If the retry worker remains alive after the bounded shutdown join:
    - ownership must remain active,
    - a later serve_forever lifetime must not start another retry worker,
    - once the old worker exits, the test can cleanly terminate.
    """

    first_base_entered = threading.Event()
    release_first_base = threading.Event()

    second_base_entered = threading.Event()
    release_second_base = threading.Event()

    retry_entered = threading.Event()
    release_retry = threading.Event()

    retry_lock = threading.Lock()
    retry_threads: set[threading.Thread] = set()

    base_lock = threading.Lock()
    base_entries = 0

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
            assert release_first_base.wait(3.0)
            return

        if entry == 2:
            second_base_entered.set()
            assert release_second_base.wait(3.0)
            return

        raise AssertionError(
            f"Unexpected base serve_forever entry: {entry}"
        )

    def blocking_retry():
        with retry_lock:
            retry_threads.add(threading.current_thread())

        retry_entered.set()

        assert release_retry.wait(3.0)
        return []

    monkeypatch.setattr(
        ThreadingHTTPServer,
        "serve_forever",
        fake_base_serve_forever,
    )
    monkeypatch.setattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        blocking_retry,
    )

    server = portal.serve_portal(
        host="127.0.0.1",
        port=0,
    )

    first = threading.Thread(
        target=server.serve_forever,
        name="3k7m-first-server-lifetime",
        daemon=True,
    )

    second = threading.Thread(
        target=server.serve_forever,
        name="3k7m-second-server-lifetime",
        daemon=True,
    )

    try:
        first.start()

        assert first_base_entered.wait(1.0)
        assert retry_entered.wait(1.0)

        # End the HTTP lifetime while deliberately keeping the retry
        # authority blocked. Production currently performs a bounded
        # one-second join on this worker.
        release_first_base.set()

        first.join(timeout=2.0)

        assert not first.is_alive(), (
            "The first serve_forever lifetime did not return after "
            "its bounded retry-worker join."
        )

        with retry_lock:
            old_workers = set(retry_threads)

        assert len(old_workers) == 1
        old_worker = next(iter(old_workers))

        assert old_worker.is_alive(), (
            "Failure injection did not keep the old retry worker alive "
            "past the bounded join."
        )

        assert server._whatsapp_retry_owner_active is True, (
            "Retry ownership was released even though the retry worker "
            "survived the bounded shutdown join."
        )

        # A second HTTP lifetime may still delegate to the base server,
        # but it must not create another retry owner while the old
        # worker remains alive.
        second.start()

        assert second_base_entered.wait(1.0)

        with retry_lock:
            workers_after_second_entry = set(retry_threads)

        assert workers_after_second_entry == old_workers, (
            "A second retry worker was created while the previous "
            "retry worker was still alive."
        )

    finally:
        release_retry.set()
        release_first_base.set()
        release_second_base.set()

        first.join(timeout=2.0)

        if second.ident is not None:
            second.join(timeout=2.0)

        server.server_close()

    assert not first.is_alive()
    assert not second.is_alive()
