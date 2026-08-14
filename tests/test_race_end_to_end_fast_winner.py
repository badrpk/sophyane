from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic, sleep

from sophyane.race_adapters import ProgressProposal
from sophyane.race_orchestrator import run_adaptive_race


def _worker(
    *,
    engine: str,
    delay: float,
    confidence: float,
    finished: Event | None = None,
):
    """
    Return a CooperativeRace-compatible worker without invoking
    any provider, model, network, browser, or SLI acquisition.
    """

    def worker(stop, report):
        try:
            sleep(delay)

            proposal = ProgressProposal(
                engine=engine,
                payload={
                    "engine": engine,
                    "mocked": True,
                },
                kind="plan",
                confidence=confidence,
                evidence=(
                    f"mocked {engine} evidence",
                ),
                requires_write=False,
            )

            return proposal

        finally:
            if finished is not None:
                finished.set()

    return worker


def test_run_adaptive_race_returns_fast_sli_without_waiting_for_slow_peers(
    tmp_path: Path,
):
    """
    Full orchestration proof.

    SLI returns quickly with a valid proposal.

    Local and cloud deliberately remain active for 2 seconds.
    run_adaptive_race() must return the SLI result without waiting
    for those already-running loser workers.
    """

    local_finished = Event()
    cloud_finished = Event()

    workers = {
        "sli": _worker(
            engine="sli",
            delay=0.02,
            confidence=0.90,
        ),
        "local": _worker(
            engine="local",
            delay=2.0,
            confidence=0.70,
            finished=local_finished,
        ),
        "cloud": _worker(
            engine="cloud",
            delay=2.0,
            confidence=0.80,
            finished=cloud_finished,
        ),
    }

    started = monotonic()

    result = run_adaptive_race(
        "repair failing pytest production code",
        workspace=tmp_path,
        config={},
        timeout=5.0,
        minimum_score=0.55,
        winner_grace_seconds=0.05,
        workers=workers,
    )

    elapsed = monotonic() - started

    assert result.ok
    assert result.winner is not None
    assert result.winner.worker == "sli"

    assert result.winner.value.engine == "sli"

    # Critical end-to-end contract:
    # orchestration must not wait for either 2-second loser.
    assert elapsed < 0.75, (
        f"adaptive race blocked for {elapsed:.3f}s"
    )

    assert not local_finished.is_set()
    assert not cloud_finished.is_set()


def test_run_adaptive_race_can_promote_stronger_peer_inside_grace_window(
    tmp_path: Path,
):
    """
    Protect bounded competitive semantics.

    SLI finishes first, but a stronger local proposal finishing
    effectively simultaneously inside the grace window may win.
    """

    workers = {
        "sli": _worker(
            engine="sli",
            delay=0.01,
            confidence=0.70,
        ),
        "local": _worker(
            engine="local",
            delay=0.03,
            confidence=0.95,
        ),
        "cloud": _worker(
            engine="cloud",
            delay=1.5,
            confidence=0.60,
        ),
    }

    started = monotonic()

    result = run_adaptive_race(
        "repair failing pytest production code",
        workspace=tmp_path,
        config={},
        timeout=5.0,
        minimum_score=0.55,
        winner_grace_seconds=0.10,
        workers=workers,
    )

    elapsed = monotonic() - started

    assert result.ok
    assert result.winner is not None
    assert result.winner.worker == "local"

    assert elapsed < 0.75, (
        f"grace-window race blocked for {elapsed:.3f}s"
    )


def test_zero_grace_end_to_end_returns_first_valid_sli(
    tmp_path: Path,
):
    """
    With the orchestrator grace window disabled, the first valid
    SLI completion must return immediately even when slower peers
    have stronger confidence.
    """

    workers = {
        "sli": _worker(
            engine="sli",
            delay=0.01,
            confidence=0.65,
        ),
        "local": _worker(
            engine="local",
            delay=1.5,
            confidence=0.99,
        ),
        "cloud": _worker(
            engine="cloud",
            delay=1.5,
            confidence=0.99,
        ),
    }

    started = monotonic()

    result = run_adaptive_race(
        "repair failing pytest production code",
        workspace=tmp_path,
        config={},
        timeout=5.0,
        minimum_score=0.55,
        winner_grace_seconds=0.0,
        workers=workers,
    )

    elapsed = monotonic() - started

    assert result.ok
    assert result.winner is not None
    assert result.winner.worker == "sli"

    assert elapsed < 0.50, (
        f"zero-grace adaptive race blocked for {elapsed:.3f}s"
    )
