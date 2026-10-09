from __future__ import annotations

import inspect
import threading

import sophyane.cloud.messaging as messaging


def test_future_tracking_exposes_dedicated_lock():
    lock_factory = getattr(
        messaging,
        "_whatsapp_inbound_futures_lock",
        None,
    )

    assert callable(lock_factory)

    first = lock_factory()
    second = lock_factory()

    assert first is second


def test_future_tracking_exposes_single_mutation_authority():
    assert callable(
        getattr(
            messaging,
            "_track_whatsapp_inbound_future",
            None,
        )
    )

    assert callable(
        getattr(
            messaging,
            "_untrack_whatsapp_inbound_future",
            None,
        )
    )

    assert callable(
        getattr(
            messaging,
            "_snapshot_whatsapp_inbound_futures",
            None,
        )
    )

    assert callable(
        getattr(
            messaging,
            "_clear_whatsapp_inbound_futures",
            None,
        )
    )


def test_tracking_helpers_use_same_lock():
    names = (
        "_track_whatsapp_inbound_future",
        "_untrack_whatsapp_inbound_future",
        "_snapshot_whatsapp_inbound_futures",
        "_clear_whatsapp_inbound_futures",
    )

    for name in names:
        fn = getattr(
            messaging,
            name,
            None,
        )

        assert callable(fn)

        source = inspect.getsource(fn)

        assert (
            "with _whatsapp_inbound_futures_lock():"
            in source
        )


def test_runtime_paths_do_not_mutate_future_set_directly():
    functions = (
        messaging.enqueue_whatsapp_inbound_message,
        messaging._replay_whatsapp_inbound_spool,
        messaging._whatsapp_inbound_future_done,
        messaging._reset_whatsapp_inbound_worker_for_tests,
    )

    forbidden = (
        "_whatsapp_inbound_futures.add(",
        "_whatsapp_inbound_futures.discard(",
        "_whatsapp_inbound_futures.clear(",
    )

    for fn in functions:
        source = inspect.getsource(fn)

        for pattern in forbidden:
            assert pattern not in source, (
                f"{fn.__name__} bypasses synchronized "
                f"future tracking via {pattern}"
            )


def test_worker_drain_and_reset_use_synchronized_tracking_authority():
    drain_source = inspect.getsource(
        messaging._drain_whatsapp_inbound_worker_for_tests
    )
    reset_source = inspect.getsource(
        messaging._reset_whatsapp_inbound_worker_for_tests
    )

    assert (
        "_snapshot_whatsapp_inbound_futures()"
        in drain_source
    )

    assert (
        "tuple(_whatsapp_inbound_futures)"
        not in drain_source
    )

    assert (
        "_clear_whatsapp_inbound_futures()"
        in reset_source
    )

    assert (
        "_whatsapp_inbound_futures.clear()"
        not in reset_source
    )


def test_future_tracking_helpers_are_thread_safe():
    track = getattr(
        messaging,
        "_track_whatsapp_inbound_future",
        None,
    )
    untrack = getattr(
        messaging,
        "_untrack_whatsapp_inbound_future",
        None,
    )
    snapshot = getattr(
        messaging,
        "_snapshot_whatsapp_inbound_futures",
        None,
    )
    clear = getattr(
        messaging,
        "_clear_whatsapp_inbound_futures",
        None,
    )

    assert callable(track)
    assert callable(untrack)
    assert callable(snapshot)
    assert callable(clear)

    clear()

    futures = [
        object()
        for _ in range(128)
    ]

    barrier = threading.Barrier(9)
    errors = []

    def add_worker(offset):
        try:
            barrier.wait()

            for index in range(
                offset,
                len(futures),
                4,
            ):
                track(futures[index])
        except BaseException as exc:
            errors.append(exc)

    def observe_worker():
        try:
            barrier.wait()

            for _ in range(500):
                snapshot()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(
            target=add_worker,
            args=(offset,),
        )
        for offset in range(4)
    ]

    threads.extend(
        threading.Thread(
            target=observe_worker,
        )
        for _ in range(4)
    )

    for thread in threads:
        thread.start()

    barrier.wait()

    for thread in threads:
        thread.join()

    assert errors == []

    assert set(snapshot()) == set(futures)

    barrier = threading.Barrier(9)
    errors.clear()

    def remove_worker(offset):
        try:
            barrier.wait()

            for index in range(
                offset,
                len(futures),
                4,
            ):
                untrack(futures[index])
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(
            target=remove_worker,
            args=(offset,),
        )
        for offset in range(4)
    ]

    threads.extend(
        threading.Thread(
            target=observe_worker,
        )
        for _ in range(4)
    )

    for thread in threads:
        thread.start()

    barrier.wait()

    for thread in threads:
        thread.join()

    assert errors == []
    assert snapshot() == ()


def test_future_tracking_contract_does_not_use_outbound_outbox():
    module_source = inspect.getsource(
        messaging._whatsapp_inbound_future_done
    )

    assert "WA_OUTBOX" not in module_source
