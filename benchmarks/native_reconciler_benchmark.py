"""Reproducible native reconciler benchmark using a temporary SQLite database."""

import argparse
import importlib.util
import json
import os
import tempfile
import threading
import time
from pathlib import Path


def load_reconciler():
    roots = []
    build_lib = os.environ.get("SOPHYANE_NATIVE_BUILD_LIB")
    if build_lib:
        roots.append(Path(build_lib) / "sophyane/native")
    roots.append(Path("src/sophyane/native"))
    candidates = [candidate for root in roots for candidate in root.glob("_reconciler*.so")]
    if not candidates:
        raise RuntimeError("build the native extension before running this benchmark")
    spec = importlib.util.spec_from_file_location("sophyane.native._reconciler", candidates[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Reconciler


def percentile(values, percentile_value):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile_value / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run(events, producers):
    Reconciler = load_reconciler()
    with tempfile.TemporaryDirectory(prefix="sophyane-native-bench-") as directory:
        database = Path(directory) / "events.sqlite3"
        reconciler = Reconciler(str(database))
        start = time.perf_counter()

        def produce(offset, count):
            for sequence in range(offset, offset + count):
                while not reconciler.submit(sequence, sequence, b"benchmark"):
                    time.sleep(0)

        per_producer = events // producers
        remainder = events % producers
        threads = []
        errors = []
        errors_lock = threading.Lock()
        offset = 0
        for index in range(producers):
            count = per_producer + (index < remainder)
            def run_producer(start, amount):
                try:
                    produce(start, amount)
                except BaseException as error:
                    with errors_lock:
                        errors.append(error)

            thread = threading.Thread(target=run_producer, args=(offset, count))
            thread.start()
            threads.append(thread)
            offset += count
        for thread in threads:
            thread.join()
        if errors:
            raise RuntimeError("benchmark producer failed") from errors[0]
        reconciler.close()
        elapsed = time.perf_counter() - start
        stats = reconciler.stats()

    latencies_ms = [value / 1_000_000.0 for value in stats["commit_latencies_ns"]]
    committed = stats["committed"]
    throughput = committed / elapsed if elapsed else 0.0
    p99 = percentile(latencies_ms, 99)
    return {
        "events": events,
        "producers": producers,
        "accepted": stats["accepted"],
        "written": stats["written"],
        "committed": committed,
        "rejected": stats["rejected"],
        "failed": stats["failed"],
        "elapsed_seconds": elapsed,
        "committed_transactions_per_sec": throughput,
        "commit_latency_ms": {
            "p50": percentile(latencies_ms, 50),
            "p95": percentile(latencies_ms, 95),
            "p99": p99,
        },
        "targets": {
            "100000_transactions_per_sec": throughput >= 100_000 and committed == events,
            "p99_under_5ms": p99 is not None and p99 < 5.0 and committed == events,
        },
        "python_reconciler": "not found in repository search",
        "database": "temporary SQLite database; removed after run",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100_000)
    parser.add_argument("--producers", type=int, default=4)
    args = parser.parse_args()
    if args.events <= 0 or args.producers <= 0:
        parser.error("events and producers must be positive")
    print(json.dumps(run(args.events, args.producers), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
