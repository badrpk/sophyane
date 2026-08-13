from __future__ import annotations

from threading import Event
from time import monotonic, sleep

from sophyane.race_runtime import AdaptiveRace


def _validator(worker, value):
    return True, float(value["score"]), (worker,)


def test_fast_winner_does_not_wait_for_slow_loser():
    """
    A valid fast worker must allow AdaptiveRace.run() to return
    without waiting for a slow loser to finish.

    No real model/network request is used.
    """

    slow_finished = Event()

    def fast(stop, report):
        sleep(0.02)
        return {
            "name": "fast",
            "score": 10.0,
        }

    def slow(stop, report):
        try:
            # Deliberately ignore stop long enough to expose a
            # blocking executor shutdown.
            sleep(2.0)
            return {
                "name": "slow",
                "score": 1.0,
            }
        finally:
            slow_finished.set()

    race = AdaptiveRace(
        validator=_validator,
        minimum_score=1.0,
        winner_grace_seconds=0.05,
    )

    started = monotonic()

    result = race.run(
        {
            "fast": fast,
            "slow": slow,
        },
        timeout=5.0,
    )

    elapsed = monotonic() - started

    assert result.winner is not None
    assert result.winner.worker == "fast"

    # Critical contract:
    # run() must not wait for the 2-second loser.
    assert elapsed < 0.75, (
        f"fast winner blocked for {elapsed:.3f}s"
    )

    # At return time the deliberately uncooperative loser should
    # normally still be running. This proves return did not depend
    # on loser completion.
    assert not slow_finished.is_set()


def test_grace_window_can_promote_stronger_near_simultaneous_winner():
    """
    A stronger candidate completing inside the bounded grace
    window may replace the initial valid front-runner.
    """

    def first(stop, report):
        sleep(0.01)
        return {
            "name": "first",
            "score": 10.0,
        }

    def stronger(stop, report):
        sleep(0.03)
        return {
            "name": "stronger",
            "score": 20.0,
        }

    race = AdaptiveRace(
        validator=_validator,
        minimum_score=1.0,
        winner_grace_seconds=0.10,
    )

    result = race.run(
        {
            "first": first,
            "stronger": stronger,
        },
        timeout=2.0,
    )

    assert result.winner is not None
    assert result.winner.worker == "stronger"
    assert result.winner.score == 20.0


def test_zero_grace_returns_first_valid_completion():
    """
    With grace disabled, a first valid completion should return
    immediately rather than waiting for a stronger slow worker.
    """

    def fast(stop, report):
        sleep(0.01)
        return {
            "name": "fast",
            "score": 10.0,
        }

    def stronger_but_slow(stop, report):
        sleep(1.5)
        return {
            "name": "stronger",
            "score": 100.0,
        }

    race = AdaptiveRace(
        validator=_validator,
        minimum_score=1.0,
        winner_grace_seconds=0.0,
    )

    started = monotonic()

    result = race.run(
        {
            "fast": fast,
            "stronger": stronger_but_slow,
        },
        timeout=5.0,
    )

    elapsed = monotonic() - started

    assert result.winner is not None
    assert result.winner.worker == "fast"

    assert elapsed < 0.50, (
        f"zero-grace winner blocked for {elapsed:.3f}s"
    )
