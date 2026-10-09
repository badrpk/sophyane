from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def test_retry_thread_start_failure_releases_owner_for_later_lifetime(
    monkeypatch,
):
    """
    Retry-owner acquisition is atomic with retry-thread startup.

    If the retry worker cannot start:
    - serve_forever propagates the startup failure,
    - owner-active state must be rolled back,
    - the base HTTP serve loop must not start for that failed lifetime,
    - a later serve_forever call must be able to acquire a fresh owner.
    """

    real_thread_start = threading.Thread.start

    retry_start_attempts = 0
    base_entries = 0
    retry_calls = 0

    retry_seen = threading.Event()
    base_entered = threading.Event()
    release_base = threading.Event()

    def controlled_start(self):
        nonlocal retry_start_attempts

        if self.name == "sophyane-whatsapp-live-retry":
            retry_start_attempts += 1

            if retry_start_attempts == 1:
                raise RuntimeError(
                    "synthetic retry thread start failure"
                )

        return real_thread_start(self)

    def fake_base_serve_forever(
        self,
        *args,
        **kwargs,
    ):
        nonlocal base_entries
        base_entries += 1
        base_entered.set()
        assert release_base.wait(2.0)

    def fake_retry():
        nonlocal retry_calls
        retry_calls += 1
        retry_seen.set()
        return []

    monkeypatch.setattr(
        threading.Thread,
        "start",
        controlled_start,
    )
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

    try:
        with pytest.raises(
            RuntimeError,
            match="synthetic retry thread start failure",
        ):
            server.serve_forever()

        assert retry_start_attempts == 1
        assert base_entries == 0
        assert retry_calls == 0

        assert server._whatsapp_retry_owner_active is False, (
            "Retry-thread startup failed but the server retained "
            "stale retry ownership."
        )

        later = threading.Thread(
            target=server.serve_forever,
            name="3k7k-later-server-lifetime",
            daemon=True,
        )

        later.start()

        try:
            assert retry_seen.wait(1.0), (
                "A later server lifetime could not acquire retry "
                "ownership after the earlier start failure."
            )

            assert base_entered.wait(1.0), (
                "The later server lifetime acquired retry ownership "
                "but did not enter the base HTTP serve loop."
            )

            assert retry_start_attempts == 2
            assert base_entries == 1
            assert retry_calls >= 1
        finally:
            release_base.set()
            later.join(timeout=2.0)

        assert not later.is_alive()
        assert server._whatsapp_retry_owner_active is False

    finally:
        release_base.set()
        server.server_close()
