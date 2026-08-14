from __future__ import annotations

import time

import pytest

from sophyane.race_adapters import (
    CooperativeRace,
    ProgressProposal,
    WorkspaceWriteLease,
    proposal_worker,
)


def test_exclusive_write_lease(
    tmp_path,
):
    lease = WorkspaceWriteLease(
        tmp_path
    )

    assert lease.acquire("sli")
    assert lease.owner == "sli"

    assert not lease.acquire(
        "cloud"
    )

    lease.assert_owner(
        "sli"
    )

    with pytest.raises(
        PermissionError
    ):
        lease.assert_owner(
            "cloud"
        )


def test_lease_transfer(
    tmp_path,
):
    lease = WorkspaceWriteLease(
        tmp_path
    )

    assert lease.acquire(
        "sli"
    )

    first_generation = (
        lease.generation
    )

    assert lease.transfer(
        "sli",
        "local",
    )

    assert lease.owner == "local"

    assert (
        lease.generation
        > first_generation
    )


def test_fast_valid_sli_can_win(
    tmp_path,
):
    race = CooperativeRace(
        tmp_path,
        winner_grace_seconds=0.01,
    )

    def sli():
        time.sleep(0.02)

        return ProgressProposal(
            engine="sli",
            payload={
                "route": "harness_execution"
            },
            kind="acquisition",
            confidence=0.82,
            evidence=(
                "behavioral validation passed",
            ),
            requires_write=True,
        )

    def local():
        time.sleep(0.20)

        return ProgressProposal(
            engine="local",
            payload={
                "action": "write_file"
            },
            kind="action",
            confidence=0.92,
            evidence=(
                "valid JSON action",
            ),
            requires_write=True,
        )

    result = race.run(
        {
            "sli": proposal_worker(
                "sli",
                sli,
            ),
            "local": proposal_worker(
                "local",
                local,
            ),
        },
        timeout=1.0,
    )

    assert result.winner is not None
    assert result.winner.worker == "sli"
    assert race.lease.owner == "sli"


def test_invalid_fast_worker_cannot_win(
    tmp_path,
):
    race = CooperativeRace(
        tmp_path
    )

    def bad_local():
        return ProgressProposal(
            engine="local",
            payload={},
            kind="invalid_kind",
            confidence=1.0,
            evidence=(
                "fast but invalid",
            ),
            requires_write=True,
        )

    def cloud():
        time.sleep(0.02)

        return ProgressProposal(
            engine="cloud",
            payload={
                "action": "run"
            },
            kind="action",
            confidence=0.80,
            evidence=(
                "normalized executable action",
            ),
            requires_write=True,
        )

    result = race.run(
        {
            "local": proposal_worker(
                "local",
                bad_local,
            ),
            "cloud": proposal_worker(
                "cloud",
                cloud,
            ),
        },
        timeout=1.0,
    )

    assert result.winner is not None
    assert result.winner.worker == "cloud"
    assert race.lease.owner == "cloud"


def test_read_only_result_gets_no_lease(
    tmp_path,
):
    race = CooperativeRace(
        tmp_path
    )

    result = race.run(
        {
            "sli": proposal_worker(
                "sli",
                lambda: ProgressProposal(
                    engine="sli",
                    payload="answer",
                    kind="answer",
                    confidence=0.90,
                    evidence=(
                        "validated source result",
                    ),
                    requires_write=False,
                ),
            ),
        },
        timeout=1.0,
    )

    assert result.winner is not None
    assert race.lease.owner is None


def test_cloud_failure_does_not_block_local(
    tmp_path,
):
    race = CooperativeRace(
        tmp_path
    )

    def cloud():
        raise RuntimeError(
            "429 quota exceeded"
        )

    def local():
        time.sleep(0.02)

        return ProgressProposal(
            engine="local",
            payload={
                "action": "inspect"
            },
            kind="action",
            confidence=0.80,
            evidence=(
                "local action valid",
            ),
            requires_write=False,
        )

    result = race.run(
        {
            "cloud": proposal_worker(
                "cloud",
                cloud,
            ),
            "local": proposal_worker(
                "local",
                local,
            ),
        },
        timeout=1.0,
    )

    assert result.winner is not None
    assert result.winner.worker == "local"
    assert "cloud" in result.errors
