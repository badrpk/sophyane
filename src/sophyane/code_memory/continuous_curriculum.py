"""Indefinite coverage-driven Sophyane SLI curriculum runner."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import random
import signal
import sys
import time
import traceback

from pathlib import Path


MEMORY_ROOT = (
    Path.home()
    / ".local/share/sophyane/code_memory"
)

CURRICULUM_ROOT = (
    MEMORY_ROOT
    / "coverage_curriculum"
)

LOCK_FILE = (
    CURRICULUM_ROOT
    / "runner.lock"
)

PID_FILE = (
    CURRICULUM_ROOT
    / "runner.pid"
)

HEARTBEAT_FILE = (
    CURRICULUM_ROOT
    / "heartbeat.json"
)


def _write_atomic(
    path: Path,
    value: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        value,
        encoding="utf-8",
    )

    temporary.replace(
        path
    )


def _heartbeat(
    **fields,
) -> None:
    payload = {
        "timestamp":
            time.time(),

        "pid":
            os.getpid(),

        **fields,
    }

    _write_atomic(
        HEARTBEAT_FILE,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def _print_coverage() -> None:
    from sophyane.code_memory.coverage_curriculum import (
        coverage_report,
    )

    report = coverage_report()

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )


def run(
    *,
    minimum_sleep: float,
    maximum_sleep: float,
    max_iterations: int | None,
) -> int:
    from sophyane.code_memory.curriculum_bridge import (
        adapt_request,
        install_background_browser_block,
        install_search_query_patch,
    )

    install_background_browser_block()

    from sophyane.code_memory.continuous_sli_loop import (
        execute_instruction,
    )
    from sophyane.code_memory.coverage_curriculum import (
        choose_next_request,
        load_state,
        record_outcome,
        save_state,
    )

    os.environ[
        "SOPHYANE_DISABLE_BROWSER_OPEN"
    ] = "1"

    os.environ[
        "SOPHYANE_NO_AUTO_OPEN"
    ] = "1"

    os.environ[
        "SOPHYANE_BROWSER_PREVIEW"
    ] = "0"

    os.environ[
        "SOPHYANE_CONTINUOUS_AUTO_PREVIEW"
    ] = "0"

    os.environ[
        "SOPHYANE_SESSION_MODE"
    ] = "sli_chunks"

    os.environ[
        "SOPHYANE_SLI_ONLY"
    ] = "1"

    CURRICULUM_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock_handle = LOCK_FILE.open(
        "a+",
        encoding="utf-8",
    )

    try:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX
            | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        print(
            "Another coverage curriculum runner is active.",
            file=sys.stderr,
        )
        return 2

    _write_atomic(
        PID_FILE,
        str(os.getpid())
        + "\n",
    )

    stopped = False

    def stop_handler(
        _signal_number,
        _frame,
    ):
        nonlocal stopped
        stopped = True

    signal.signal(
        signal.SIGINT,
        stop_handler,
    )
    signal.signal(
        signal.SIGTERM,
        stop_handler,
    )

    state = load_state()

    if not state.seed:
        state.seed = int(
            time.time()
        )

    save_state(
        state
    )

    completed = 0

    print(
        "Coverage-driven SLI curriculum started.",
        flush=True,
    )

    print(
        f"State: {CURRICULUM_ROOT}",
        flush=True,
    )

    while not stopped:
        if (
            max_iterations is not None
            and completed >= max_iterations
        ):
            break

        family = None
        request = None
        started = time.time()

        try:
            (
                family,
                request,
                ranked,
            ) = choose_next_request(
                state
            )

            _successes = int(
                state.family_successes.get(
                    family.name,
                    0,
                )
            )

            _failure_streak = int(
                state.failure_streaks.get(
                    family.name,
                    0,
                )
            )

            _cursor = int(
                state.family_cursor.get(
                    family.name,
                    0,
                )
            )

            _bridge = adapt_request(
                family.name,
                request,
                successes=_successes,
                failure_streak=_failure_streak,
                cursor=_cursor,
            )

            original_request = request
            request = _bridge.adapted

            install_search_query_patch(
                _bridge.search_identity
            )

            top_summary = [
                {
                    "family":
                        item.family,

                    "score":
                        round(
                            item.score,
                            2,
                        ),

                    "successes":
                        item.successes,

                    "failures":
                        item.failures,

                    "memory":
                        item.memory_evidence,
                }
                for item in ranked[:5]
            ]

            _heartbeat(
                status="running",
                iteration=state.iteration + 1,
                family=family.name,
                request=request,
                top_families=top_summary,
            )

            print()
            print("=" * 76)
            print(
                f"CURRICULUM ITERATION {state.iteration + 1}"
            )
            print(
                f"Family : {family.name}"
            )
            print(
                f"Request: {request}"
            )
            print(
                f"Bridge : level={_bridge.level}; "
                f"identity={_bridge.search_identity or 'n/a'}; "
                f"reason={_bridge.reason}"
            )
            if original_request != request:
                print(
                    f"Original curriculum request: {original_request}"
                )
            print("=" * 76)
            print(
                "Top weak families:",
                json.dumps(
                    top_summary,
                    ensure_ascii=False,
                ),
            )

            event = execute_instruction(
                request,
                progress=lambda message:
                    print(
                        f"[SLI] {message}",
                        flush=True,
                    ),
            )

            elapsed = (
                time.time()
                - started
            )

            record = record_outcome(
                state,
                family=family,
                request=request,
                success=event.success,
                chunks_learned=event.chunks_learned,
                elapsed_seconds=elapsed,
                workspace=event.workspace,
                report=event.report,
            )

            print()
            print(
                "Curriculum result:",
                json.dumps(
                    {
                        "family":
                            family.name,

                        "success":
                            event.success,

                        "files":
                            len(
                                event.files
                            ),

                        "bytes":
                            event.bytes_generated,

                        "chunks_learned":
                            event.chunks_learned,

                        "seconds":
                            round(
                                elapsed,
                                2,
                            ),

                        "failure_streak":
                            record[
                                "failure_streak"
                            ],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

            completed += 1

            _heartbeat(
                status="sleeping",
                iteration=state.iteration,
                family=family.name,
                request=request,
                success=event.success,
                chunks_learned=event.chunks_learned,
            )

        except KeyboardInterrupt:
            stopped = True
            break

        except Exception as error:
            elapsed = (
                time.time()
                - started
            )

            print(
                "Curriculum error:",
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
                flush=True,
            )

            traceback.print_exc()

            if (
                family is not None
                and request is not None
            ):
                record_outcome(
                    state,
                    family=family,
                    request=request,
                    success=False,
                    chunks_learned=0,
                    elapsed_seconds=elapsed,
                    workspace="",
                    report=(
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                )

            _heartbeat(
                status="error",
                error=(
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            )

        if stopped:
            break

        low = max(
            0.0,
            float(
                minimum_sleep
            ),
        )

        high = max(
            low,
            float(
                maximum_sleep
            ),
        )

        # A small jitter prevents alignment with acquisition/indexing cycles.
        sleep_seconds = random.uniform(
            low,
            high,
        )

        deadline = (
            time.time()
            + sleep_seconds
        )

        while (
            not stopped
            and time.time() < deadline
        ):
            time.sleep(
                min(
                    1.0,
                    deadline - time.time(),
                )
            )

    _heartbeat(
        status="stopped",
        iteration=state.iteration,
    )

    PID_FILE.unlink(
        missing_ok=True,
    )

    print(
        "Coverage-driven SLI curriculum stopped.",
        flush=True,
    )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Sophyane's coverage-driven "
            "continuous SLI curriculum."
        )
    )

    parser.add_argument(
        "--min-sleep",
        type=float,
        default=30.0,
        help=(
            "Minimum seconds between "
            "instructions."
        ),
    )

    parser.add_argument(
        "--max-sleep",
        type=float,
        default=90.0,
        help=(
            "Maximum seconds between "
            "instructions."
        ),
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help=(
            "Stop after this many iterations; "
            "default is indefinite."
        ),
    )

    parser.add_argument(
        "--coverage",
        action="store_true",
        help=(
            "Print capability-family coverage "
            "and exit."
        ),
    )

    arguments = parser.parse_args()

    if arguments.coverage:
        _print_coverage()
        return 0

    return run(
        minimum_sleep=arguments.min_sleep,
        maximum_sleep=arguments.max_sleep,
        max_iterations=arguments.iterations,
    )


if __name__ == "__main__":
    raise SystemExit(main())



# SOPHYANE_ADAPTIVE_CURRICULUM_BRIDGE_V1
