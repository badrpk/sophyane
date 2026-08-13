from __future__ import annotations

import time

from sophyane.race_runtime import (
    AdaptiveRace,
    RaceStatus,
)


def validator(
    worker,
    value,
):
    return (
        value["valid"],
        value["score"],
        (
            value["evidence"],
        ),
    )


def test_fastest_valid_worker_wins():
    def sli(stop, report):
        time.sleep(0.02)

        report(
            RaceStatus.PROGRESS,
            "SLI candidate acquired",
        )

        return {
            "valid": True,
            "score": 0.80,
            "evidence": "validated SLI",
        }

    def local(stop, report):
        time.sleep(0.25)

        return {
            "valid": True,
            "score": 0.95,
            "evidence": "local plan",
        }

    def cloud(stop, report):
        time.sleep(0.30)

        return {
            "valid": True,
            "score": 0.99,
            "evidence": "cloud plan",
        }

    race = AdaptiveRace(
        validator=validator,
        minimum_score=0.70,
        winner_grace_seconds=0.01,
    )

    result = race.run(
        {
            "sli": sli,
            "local": local,
            "cloud": cloud,
        },
        timeout=2.0,
    )

    assert result.ok
    assert result.winner is not None

    assert (
        result.winner.worker
        == "sli"
    )


def test_fast_invalid_worker_does_not_win():
    def sli(stop, report):
        time.sleep(0.01)

        return {
            "valid": False,
            "score": 1.00,
            "evidence": "bad candidate",
        }

    def cloud(stop, report):
        time.sleep(0.03)

        return {
            "valid": True,
            "score": 0.85,
            "evidence": "verified cloud",
        }

    race = AdaptiveRace(
        validator=validator,
        minimum_score=0.70,
    )

    result = race.run(
        {
            "sli": sli,
            "cloud": cloud,
        },
        timeout=2.0,
    )

    assert result.winner is not None

    assert (
        result.winner.worker
        == "cloud"
    )


def test_worker_failure_does_not_block_others():
    def cloud(stop, report):
        raise RuntimeError(
            "quota exceeded"
        )

    def local(stop, report):
        time.sleep(0.03)

        return {
            "valid": True,
            "score": 0.90,
            "evidence": "local survived",
        }

    race = AdaptiveRace(
        validator=validator,
        minimum_score=0.70,
    )

    result = race.run(
        {
            "cloud": cloud,
            "local": local,
        },
        timeout=2.0,
    )

    assert result.winner is not None

    assert (
        result.winner.worker
        == "local"
    )

    assert "cloud" in result.errors


def test_slow_worker_does_not_hold_up_winner():
    def local(stop, report):
        for _ in range(100):
            if stop.is_set():
                return {
                    "valid": False,
                    "score": 0,
                    "evidence": "cancelled",
                }

            time.sleep(0.02)

        return {
            "valid": True,
            "score": 1,
            "evidence": "slow",
        }

    def cloud(stop, report):
        time.sleep(0.03)

        return {
            "valid": True,
            "score": 0.90,
            "evidence": "fast",
        }

    before = time.monotonic()

    race = AdaptiveRace(
        validator=validator,
        minimum_score=0.70,
        winner_grace_seconds=0.01,
    )

    result = race.run(
        {
            "local": local,
            "cloud": cloud,
        },
        timeout=3.0,
    )

    elapsed = (
        time.monotonic()
        - before
    )

    assert result.winner is not None

    assert (
        result.winner.worker
        == "cloud"
    )

    assert elapsed < 0.5


def test_first_response_is_not_enough():
    def local(stop, report):
        time.sleep(0.01)

        return {
            "valid": True,
            "score": 0.20,
            "evidence": "weak response",
        }

    def sli(stop, report):
        time.sleep(0.03)

        return {
            "valid": True,
            "score": 0.82,
            "evidence": "objective evidence",
        }

    race = AdaptiveRace(
        validator=validator,
        minimum_score=0.70,
    )

    result = race.run(
        {
            "local": local,
            "sli": sli,
        },
        timeout=2.0,
    )

    assert result.winner is not None

    assert (
        result.winner.worker
        == "sli"
    )
