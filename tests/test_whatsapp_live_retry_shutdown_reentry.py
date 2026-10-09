from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_new_serve_lifetime_recovers_after_stopping_worker_exits(
    monkeypatch,
):
    """
    A new serve lifetime may enter while the previous retry worker is
    still alive but already stopping.

    When that old worker finally exits, retry authority must continue
    for the new active serve lifetime without creating overlapping
    retry workers.
    """

    base_lock = threading.Lock()
    base_entries = 0

    first_base_entered = threading.Event()
    second_base_entered = threading.Event()

    release_first_base = threading.Event()
    release_second_base = threading.Event()

    first_retry_entered = threading.Event()
    release_first_retry = threading.Event()

    replacement_retry_seen = threading.Event()

    retry_lock = threading.Lock()
    retry_threads: list[threading.Thread] = []
    retry_calls = 0

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
            assert release_first_base.wait(4.0)
            return

        if entry == 2:
            second_base_entered.set()
            assert release_second_base.wait(4.0)
            return

        raise AssertionError(
            f"Unexpected base serve_forever entry: {entry}"
        )

    def controlled_retry():
        nonlocal retry_calls

        current = threading.current_thread()

        with retry_lock:
            retry_calls += 1
            call_number = retry_calls

            if current not in retry_threads:
                retry_threads.append(current)

        if call_number == 1:
            first_retry_entered.set()
            assert release_first_retry.wait(4.0)
            return []

        replacement_retry_seen.set()
        return []

    monkeypatch.setattr(
        ThreadingHTTPServer,
        "serve_forever",
        fake_base_serve_forever,
    )
    monkeypatch.setattr(
        messaging,
        "_retry_whatsapp_inbound_spool",
        controlled_retry,
    )

    server = portal.serve_portal(
        host="127.0.0.1",
        port=0,
    )

    first = threading.Thread(
        target=server.serve_forever,
        name="3k7q-first-serve",
        daemon=True,
    )

    second = threading.Thread(
        target=server.serve_forever,
        name="3k7q-second-serve",
        daemon=True,
    )

    try:
        # Lifetime 1 owns the first retry worker.
        first.start()

        assert first_base_entered.wait(1.0)
        assert first_retry_entered.wait(1.0)

        with retry_lock:
            assert len(retry_threads) == 1
            old_worker = retry_threads[0]

        # Last active serve exits. Its finally requests retry shutdown,
        # but controlled_retry deliberately prevents the worker from
        # observing that stop request before the one-second join ends.
        release_first_base.set()

        first.join(timeout=2.0)

        assert not first.is_alive(), (
            "First HTTP lifetime did not return after bounded join."
        )

        assert old_worker.is_alive(), (
            "Failure injection did not preserve the old retry worker "
            "past the bounded join."
        )

        assert server._serve_forever_active_count == 0
        assert server._whatsapp_retry_owner_active is True

        # Reenter while the old/stopping worker is still published as
        # owner. Current production therefore does not start a new one.
        second.start()

        assert second_base_entered.wait(1.0)
        assert second.is_alive()

        assert server._serve_forever_active_count == 1

        with retry_lock:
            assert retry_threads == [old_worker], (
                "A replacement worker overlapped the old retry worker."
            )

        # Now allow the old worker to return. Because its stop event was
        # already set by lifetime 1, it should terminate immediately
        # after this retry call.
        release_first_retry.set()

        # R performs the shutdown-to-reentry handoff in place:
        # the same retry worker observes that lifetime 2 became active,
        # installs a fresh stop event, and continues retry authority.
        assert replacement_retry_seen.wait(0.5), (
            "The stopping retry worker did not resume retry authority "
            "for the new active serve_forever lifetime."
        )

        assert old_worker.is_alive(), (
            "The retry worker terminated instead of performing the "
            "in-place shutdown-to-reentry handoff."
        )

        # Lifetime 2 is still active and must retain the same singular
        # retry worker. No overlapping replacement thread is permitted.
        assert second.is_alive()
        assert server._serve_forever_active_count == 1

        with retry_lock:
            assert retry_threads == [old_worker], (
                "Shutdown-to-reentry handoff created an overlapping "
                "retry worker instead of continuing the existing one."
            )

        assert server._whatsapp_retry_owner_active is True
        assert server._whatsapp_retry_thread is old_worker

    finally:
        release_first_retry.set()
        release_first_base.set()
        release_second_base.set()

        first.join(timeout=2.0)

        if second.ident is not None:
            second.join(timeout=2.0)

        server.server_close()

    assert not first.is_alive()
    assert not second.is_alive()
