from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import mode6_ladder as ladder  # noqa: E402
from mode6_failure_supervisor import FaultDomain  # noqa: E402


def _failing_level():
    return ladder.Level(
        99,
        "causal-test",
        "synthetic request",
        lambda before: (_ for _ in ()).throw(
            ladder.VerificationFailure("synthetic red")
        ),
    )


def test_sophyane_branch_captures_its_own_repair_boundary(monkeypatch):
    level = _failing_level()

    snapshots = iter(
        [
            {"src/sophyane/a.py": "before"},
            {"mode6_ladder_workspace/challenge.txt": "before"},
            {"src/sophyane/a.py": "after"},
            {"mode6_ladder_workspace/challenge.txt": "before"},
        ]
    )

    monkeypatch.setattr(
        ladder,
        "snapshot_subtree",
        lambda prefix: next(snapshots),
    )

    monkeypatch.setattr(
        ladder,
        "shell_command",
        lambda command, request: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    monkeypatch.setattr(
        ladder,
        "classify_failure",
        lambda **kwargs: FaultDomain.SOPHYANE,
    )

    monkeypatch.setattr(
        ladder,
        "run_cloud_repair",
        lambda **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="repair ok",
            stderr="",
        ),
    )

    monkeypatch.setattr(
        ladder,
        "critical_repair_succeeded",
        lambda result: True,
    )

    events = []
    monkeypatch.setattr(
        ladder,
        "append_journal",
        lambda event: events.append(event),
    )

    calls = {"mode6": 0}

    def shell_once_then_green(command, request):
        calls["mode6"] += 1
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        ladder,
        "shell_command",
        shell_once_then_green,
    )

    verifier_calls = {"count": 0}

    def verifier(before):
        verifier_calls["count"] += 1
        if verifier_calls["count"] == 1:
            raise ladder.VerificationFailure("synthetic red")
        return "synthetic green"

    level = ladder.Level(
        99,
        "causal-test",
        "synthetic request",
        verifier,
    )

    assert ladder.execute_level(
        level,
        command="unused",
        dry_run=False,
    ) is True

    assert any(
        event.get("event") == "sophyane_improvement_verified"
        for event in events
    )


def test_challenge_mutation_rejects_sophyane_attribution(monkeypatch):
    level = _failing_level()

    snapshots = iter(
        [
            {"src/sophyane/a.py": "before"},
            {"mode6_ladder_workspace/challenge.txt": "before"},
            {"src/sophyane/a.py": "after"},
            {"mode6_ladder_workspace/challenge.txt": "AFTER"},
        ]
    )

    monkeypatch.setattr(
        ladder,
        "snapshot_subtree",
        lambda prefix: next(snapshots),
    )

    monkeypatch.setattr(
        ladder,
        "shell_command",
        lambda command, request: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    monkeypatch.setattr(
        ladder,
        "classify_failure",
        lambda **kwargs: FaultDomain.SOPHYANE,
    )

    monkeypatch.setattr(
        ladder,
        "run_cloud_repair",
        lambda **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="repair ok",
            stderr="",
        ),
    )

    monkeypatch.setattr(
        ladder,
        "critical_repair_succeeded",
        lambda result: True,
    )

    events = []
    monkeypatch.setattr(
        ladder,
        "append_journal",
        lambda event: events.append(event),
    )

    assert ladder.execute_level(
        level,
        command="unused",
        dry_run=False,
    ) is False

    rejected = [
        event
        for event in events
        if event.get("event")
        == "sophyane_improvement_rejected"
    ]

    assert rejected
    assert rejected[-1]["reason"] == (
        "challenge_mutated_during_repair"
    )


def test_no_source_delta_rejects_sophyane_attribution(monkeypatch):
    level = _failing_level()

    snapshots = iter(
        [
            {"src/sophyane/a.py": "same"},
            {"mode6_ladder_workspace/challenge.txt": "same"},
            {"src/sophyane/a.py": "same"},
            {"mode6_ladder_workspace/challenge.txt": "same"},
        ]
    )

    monkeypatch.setattr(
        ladder,
        "snapshot_subtree",
        lambda prefix: next(snapshots),
    )

    monkeypatch.setattr(
        ladder,
        "shell_command",
        lambda command, request: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    monkeypatch.setattr(
        ladder,
        "classify_failure",
        lambda **kwargs: FaultDomain.SOPHYANE,
    )

    monkeypatch.setattr(
        ladder,
        "run_cloud_repair",
        lambda **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="repair ok",
            stderr="",
        ),
    )

    monkeypatch.setattr(
        ladder,
        "critical_repair_succeeded",
        lambda result: True,
    )

    events = []
    monkeypatch.setattr(
        ladder,
        "append_journal",
        lambda event: events.append(event),
    )

    assert ladder.execute_level(
        level,
        command="unused",
        dry_run=False,
    ) is False

    rejected = [
        event
        for event in events
        if event.get("event")
        == "sophyane_improvement_rejected"
    ]

    assert rejected
    assert rejected[-1]["reason"] == "no_sophyane_source_delta"
