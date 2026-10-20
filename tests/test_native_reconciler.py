import importlib.util
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest


def load_reconciler():
    build_lib = os.environ.get("SOPHYANE_NATIVE_BUILD_LIB")
    roots = [Path("src/sophyane/native")]
    if build_lib:
        roots.insert(0, Path(build_lib) / "sophyane/native")
    candidates = [candidate for root in roots for candidate in root.glob("_reconciler*.so")]
    if not candidates:
        raise ImportError("native reconciler extension has not been built")
    spec = importlib.util.spec_from_file_location(
        "sophyane.native._reconciler", candidates[0]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Reconciler


def read_events(path: Path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT sequence, timestamp_ns, value, payload "
            "FROM reconciled_events ORDER BY sequence"
        ).fetchall()


def assert_integrity(path: Path):
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_native_reconciler_drains_without_losing_accepted_events(tmp_path):
    Reconciler = load_reconciler()
    database = tmp_path / "events.sqlite3"
    reconciler = Reconciler(str(database))
    expected = 400
    assert all(
        reconciler.submit(sequence, sequence * 2, f"event-{sequence}".encode())
        for sequence in range(expected)
    )

    reconciler.close()
    stats = reconciler.stats()
    rows = read_events(database)

    assert stats["accepted"] == expected
    assert stats["written"] == expected
    assert stats["committed"] == expected
    assert stats["failed"] == 0
    assert stats["cleanup_failures"] == 0
    assert len(rows) == expected
    assert {row[0] for row in rows} == set(range(expected))
    assert_integrity(database)


def test_native_reconciler_rejects_oversized_payload_and_submissions_after_close(
    tmp_path,
):
    Reconciler = load_reconciler()
    reconciler = Reconciler(str(tmp_path / "events.sqlite3"))

    assert not reconciler.submit(1, 1, b"x" * 1025)
    reconciler.close()
    assert not reconciler.submit(2, 2, b"after-close")
    assert reconciler.stats()["rejected"] == 2


def test_native_reconciler_multithreaded_producers_and_shutdown_race(tmp_path):
    Reconciler = load_reconciler()
    database = tmp_path / "events.sqlite3"
    reconciler = Reconciler(str(database))
    accepted = []
    accepted_lock = threading.Lock()
    start = threading.Barrier(5)

    def produce(offset):
        start.wait()
        local = []
        for sequence in range(offset, offset + 250):
            if reconciler.submit(sequence, sequence, b"x"):
                local.append(sequence)
        with accepted_lock:
            accepted.extend(local)

    producers = [threading.Thread(target=produce, args=(i * 250,)) for i in range(4)]
    for producer in producers:
        producer.start()
    start.wait()
    time.sleep(0.001)
    reconciler.close()
    for producer in producers:
        producer.join()

    stats = reconciler.stats()
    assert stats["accepted"] == len(accepted)
    assert stats["committed"] == len(accepted)
    assert stats["failed"] == 0
    assert stats["cleanup_failures"] == 0
    assert len(read_events(database)) == len(set(accepted))
    assert_integrity(database)


def test_native_reconciler_duplicate_sequences_are_transactionally_committed(tmp_path):
    Reconciler = load_reconciler()
    database = tmp_path / "events.sqlite3"
    reconciler = Reconciler(str(database))
    assert reconciler.submit(7, 1, b"first")
    assert reconciler.submit(7, 2, b"second")
    reconciler.close()

    stats = reconciler.stats()
    rows = read_events(database)
    assert stats["accepted"] == stats["written"] == stats["committed"] == 2
    assert len(rows) == 1
    assert rows[0][0] == 7
    assert rows[0][2:] == (2, b"second")
    assert_integrity(database)


def test_native_reconciler_reports_database_failure_without_claiming_commit(tmp_path):
    Reconciler = load_reconciler()
    database = tmp_path / "events.sqlite3"
    reconciler = Reconciler(str(database))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_native_events BEFORE INSERT ON reconciled_events "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )

    assert reconciler.submit(1, 1, b"failure")
    reconciler.close()
    stats = reconciler.stats()
    assert stats["accepted"] == 1
    assert stats["written"] == 0
    assert stats["committed"] == 0
    assert stats["failed"] == 1
    assert read_events(database) == []
    assert_integrity(database)


def test_native_reconciler_queue_saturation_counts_rejections(tmp_path):
    Reconciler = load_reconciler()
    reconciler = Reconciler(str(tmp_path / "events.sqlite3"))
    attempts = 100_000
    accepted = sum(reconciler.submit(sequence, sequence, b"x") for sequence in range(attempts))
    reconciler.close()

    stats = reconciler.stats()
    assert stats["accepted"] == accepted
    assert stats["rejected"] == attempts - accepted
    assert stats["committed"] == accepted
    assert stats["failed"] == 0


@pytest.mark.parametrize("tool", ["clang++", "g++"])
def test_native_build_tool_is_available(tool):
    if not __import__("shutil").which(tool):
        pytest.skip(f"{tool} unavailable")
