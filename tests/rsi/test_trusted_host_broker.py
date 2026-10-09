import ast
import sys
from dataclasses import replace

import pytest

from conftest import git
from test_candidate_isolation import baseline_for
from test_automatic_promotion import setup_candidate
from test_verification_gate import passing_verification


def test_candidate_rejects_both_immutable_trust_roots(repo, tmp_path):
    from sophyane.rsi.candidate import Candidate

    candidate = Candidate.create(baseline_for(repo), tmp_path / "candidates")
    try:
        for path in (
            "src/sophyane/intelligence_authority.py",
            "src/sophyane/rsi_host_broker.py",
        ):
            with pytest.raises(PermissionError):
                candidate.apply("codex_cli", {path: "attack"}, {path})
    finally:
        candidate.cleanup()


def test_candidate_still_allows_normal_source_proposal(repo, tmp_path):
    from sophyane.rsi.candidate import Candidate

    candidate = Candidate.create(baseline_for(repo), tmp_path / "candidates")
    try:
        candidate.apply("codex_cli", {"value.py": "VALUE = 2\n"}, {"value.py"})
        assert (candidate.path / "value.py").read_text() == "VALUE = 2\n"
        assert (repo / "value.py").read_text() == "VALUE = 1\n"
    finally:
        candidate.cleanup()


def test_rsi_promotion_has_no_physical_primary_mutators():
    source = open("src/sophyane/rsi/promotion.py", encoding="utf-8").read()
    tree = ast.parse(source)
    forbidden = {"read-tree", "update-ref", "checkout", "reset", "clean"}
    calls = [
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "git"
        and len(node.args) > 1
        and isinstance(node.args[1], ast.Constant)
    ]
    assert not forbidden.intersection(calls)


def test_no_mutating_git_commands_exist_inside_mutable_rsi():
    forbidden = {"read-tree", "update-ref", "checkout", "reset", "clean"}
    for path in __import__("pathlib").Path("src/sophyane/rsi").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "git":
                continue
            values = {
                arg.value for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            }
            assert not forbidden.intersection(values), path


def test_snapshot_workspace_bypass_is_rejected(repo, tmp_path):
    from types import SimpleNamespace
    from sophyane.rsi.candidate_workspace import CandidateWorkspace

    workspace = CandidateWorkspace(repo, tmp_path / "candidates").create()
    with pytest.raises(PermissionError, match="deterministic evidence"):
        workspace.promote("codex_cli", SimpleNamespace(accepted=False), {"value.py"})
    workspace.close()


def test_broker_rejects_forged_local_provider_authority(repo, tmp_path):
    from sophyane.rsi.promotion import promote

    baseline, candidate, journal, weakness_record = setup_candidate(repo, tmp_path)
    candidate.record.provider_used = "local_gguf"
    with pytest.raises(PermissionError, match="Codex/NIFDU"):
        promote(
            baseline, candidate, weakness_record, passing_verification(),
            {"quality": 2, "latency": 1}, journal, "iteration-local",
            smoke=((sys.executable, "check.py"),),
        )
    assert git(repo, "rev-parse", "HEAD") == baseline.commit
    candidate.cleanup()


def test_broker_has_no_consensus_or_second_approval_path():
    source = open("src/sophyane/rsi_host_broker.py", encoding="utf-8").read().casefold()
    assert "consensus" not in source
    assert "second llm" not in source


def test_valid_sealed_deterministic_candidate_promotes_via_broker(repo, tmp_path):
    from sophyane.rsi.promotion import promote

    baseline, candidate, journal, weakness_record = setup_candidate(repo, tmp_path)
    result = promote(
        baseline, candidate, weakness_record, passing_verification(),
        {"quality": 2, "latency": 1}, journal, "iteration-broker",
        smoke=((sys.executable, "check.py"),),
    )
    assert result.state == "VERIFIED_BASELINE"
    assert git(repo, "rev-parse", "HEAD") == candidate.record.candidate_commit
    candidate.cleanup()


def test_false_or_missing_gate_is_rejected_before_primary_mutation(repo, tmp_path):
    from sophyane.rsi.promotion import promote

    baseline, candidate, journal, weakness_record = setup_candidate(repo, tmp_path)
    bad = replace(passing_verification(), full_regression=())
    result = promote(
        baseline, candidate, weakness_record, bad,
        {"quality": 2, "latency": 1}, journal, "iteration-gates",
        smoke=((sys.executable, "check.py"),),
    )
    assert result.state == "REJECTED"
    assert git(repo, "rev-parse", "HEAD") == baseline.commit
    candidate.cleanup()


def test_changed_candidate_after_sealing_is_rejected(repo, tmp_path):
    from sophyane.rsi.promotion import promote

    baseline, candidate, journal, weakness_record = setup_candidate(repo, tmp_path)
    (candidate.path / "value.py").write_text("VALUE = 99\n")
    with pytest.raises(ValueError):
        promote(
            baseline, candidate, weakness_record, passing_verification(),
            {"quality": 2, "latency": 1}, journal, "iteration-changed",
            smoke=((sys.executable, "check.py"),),
        )
    assert git(repo, "rev-parse", "HEAD") == baseline.commit
    candidate.cleanup()


# Trusted snapshot boundary adversarial coverage.
def _snapshot_fixture(files):
    from types import SimpleNamespace
    from sophyane.rsi_host_broker import _snapshot_fingerprint
    return SimpleNamespace(files=files, fingerprint=_snapshot_fingerprint(files))


def test_snapshot_rejects_traversal_absolute_and_trust_root_aliases(tmp_path):
    from types import SimpleNamespace
    from sophyane.rsi_host_broker import promote_snapshot, _snapshot_fingerprint
    baseline = _snapshot_fixture({"safe.txt": b"old"})
    for name in ("../escape.txt", str(tmp_path / "absolute.txt"),
                 "src/sophyane/../sophyane/intelligence_authority.py",
                 "src/sophyane/./rsi_host_broker.py"):
        candidate_files = {"safe.txt": b"old", name: b"attack"}
        candidate = _snapshot_fixture(candidate_files)
        evidence = SimpleNamespace(accepted=True, fingerprint=candidate.fingerprint)
        with pytest.raises(PermissionError):
            promote_snapshot(tmp_path, baseline, candidate, evidence, candidate_files)


def test_snapshot_rejects_symlink_parent_target_and_hardlink(tmp_path):
    from sophyane.rsi_host_broker import promote_snapshot
    outside = tmp_path.parent / "outside.txt"
    outside.write_bytes(b"outside")
    (tmp_path / "link-parent").symlink_to(tmp_path.parent, target_is_directory=True)
    baseline = _snapshot_fixture({"link-parent/outside.txt": b"outside"})
    candidate = _snapshot_fixture({"link-parent/outside.txt": b"attack"})
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    with pytest.raises(PermissionError):
        promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)
    target = tmp_path / "hard.txt"
    target.write_bytes(b"old")
    hard = tmp_path / "hard-alias.txt"
    hardlinks_supported = True
    try:
        hard.hardlink_to(target)
    except (OSError, NotImplementedError):
        hardlinks_supported = False
    if hardlinks_supported:
        baseline = _snapshot_fixture({"hard.txt": b"old"})
        candidate = _snapshot_fixture({"hard.txt": b"new"})
        evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
        with pytest.raises(PermissionError):
            promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)


def test_snapshot_freezes_candidate_bytes_before_promotion(tmp_path, monkeypatch):
    from sophyane.rsi_host_broker import promote_snapshot
    target = tmp_path / "value.txt"
    target.write_bytes(b"old")
    baseline = _snapshot_fixture({"value.txt": b"old"})
    files = {"value.txt": b"new"}
    candidate = _snapshot_fixture(files)
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    original = __import__("sophyane.rsi_host_broker", fromlist=["_canonical_snapshot_target"])._canonical_snapshot_target
    def mutate_after_freeze(repository, name):
        files["value.txt"] = b"attacker"
        return original(repository, name)
    monkeypatch.setattr("sophyane.rsi_host_broker._canonical_snapshot_target", mutate_after_freeze)
    result = promote_snapshot(tmp_path, baseline, candidate, evidence, {"value.txt"})
    assert target.read_bytes() == b"new"
    assert result.candidate["value.txt"] == b"new"


def test_snapshot_nth_write_failure_restores_exact_baseline(tmp_path, monkeypatch):
    from sophyane.rsi_host_broker import promote_snapshot
    (tmp_path / "a.txt").write_bytes(b"a0")
    (tmp_path / "b.txt").write_bytes(b"b0")
    baseline = _snapshot_fixture({"a.txt": b"a0", "b.txt": b"b0"})
    candidate = _snapshot_fixture({"a.txt": b"a1", "b.txt": b"b1"})
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    import sophyane.rsi_host_broker as broker
    real = broker._write_snapshot_atomically
    calls = [0]
    def fail_second(target, data):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("synthetic nth write failure")
        return real(target, data)
    monkeypatch.setattr(broker, "_write_snapshot_atomically", fail_second)
    with pytest.raises(OSError):
        broker.promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)
    assert (tmp_path / "a.txt").read_bytes() == b"a0"
    assert (tmp_path / "b.txt").read_bytes() == b"b0"


def test_snapshot_rollback_refuses_human_change_and_link_substitution(tmp_path):
    from sophyane.rsi_host_broker import promote_snapshot, rollback_snapshot
    target = tmp_path / "value.txt"
    target.write_bytes(b"old")
    baseline = _snapshot_fixture({"value.txt": b"old"})
    candidate = _snapshot_fixture({"value.txt": b"new"})
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    transaction = promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)
    target.write_bytes(b"human")
    with pytest.raises(ValueError):
        rollback_snapshot(transaction)
    target.unlink()
    target.symlink_to(tmp_path.parent / "human")
    with pytest.raises(ValueError):
        rollback_snapshot(transaction)



def test_snapshot_rejects_symlink_target(tmp_path):
    from sophyane.rsi_host_broker import promote_snapshot
    outside = tmp_path.parent / "target.txt"
    outside.write_bytes(b"outside")
    (tmp_path / "target.txt").symlink_to(outside)
    baseline = _snapshot_fixture({"target.txt": b"outside"})
    candidate = _snapshot_fixture({"target.txt": b"new"})
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    with pytest.raises(PermissionError):
        promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)


def test_snapshot_baseline_validation_runs_inside_lease(tmp_path, monkeypatch):
    import sophyane.rsi_host_broker as broker
    from contextlib import contextmanager
    events = []
    @contextmanager
    def lease(repository):
        events.append("lease-enter")
        yield repository
        events.append("lease-exit")
    monkeypatch.setattr(broker, "repository_mutation_lease", lease)
    original = broker._snapshot_state
    def checked(target):
        assert events == ["lease-enter"]
        return original(target)
    monkeypatch.setattr(broker, "_snapshot_state", checked)
    (tmp_path / "x").write_bytes(b"old")
    baseline = _snapshot_fixture({"x": b"old"})
    candidate = _snapshot_fixture({"x": b"new"})
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    broker.promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)
    assert events[-1] == "lease-exit"


def test_snapshot_restore_failure_emits_recovery_evidence(tmp_path, monkeypatch):
    import sophyane.rsi_host_broker as broker
    (tmp_path / "x").write_bytes(b"old")
    (tmp_path / "y").write_bytes(b"old-y")
    baseline = _snapshot_fixture({"x": b"old", "y": b"old-y"})
    candidate = _snapshot_fixture({"x": b"new", "y": b"new-y"})
    evidence = type("Evidence", (), {"accepted": True, "fingerprint": candidate.fingerprint})()
    real = broker._write_snapshot_atomically
    calls = [0]
    def fail_restore(target, data):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("promotion write failure")
        if calls[0] == 3:
            raise OSError("restore failure")
        return real(target, data)
    monkeypatch.setattr(broker, "_write_snapshot_atomically", fail_restore)
    with pytest.raises(broker.SnapshotRecoveryError) as error:
        broker.promote_snapshot(tmp_path, baseline, candidate, evidence, candidate.files)
    assert error.value.__cause__ is not None
    assert str(error.value.__cause__) == "promotion write failure"
    assert error.value.evidence_path.is_file()
    payload = __import__("json").loads(error.value.evidence_path.read_text())
    assert payload["repository"] == str(tmp_path)
    assert payload["error"] == "OSError: restore failure"
    assert payload["states"][str(tmp_path / "x")] == __import__("hashlib").sha256(b"old").hexdigest()
    assert (tmp_path / "x").read_bytes() == b"new"
    assert (tmp_path / "y").read_bytes() == b"old-y"
    error.value.evidence_path.unlink()


def test_snapshot_second_write_failure_restores_only_completed_write(tmp_path, monkeypatch):
    import sophyane.rsi_host_broker as broker

    (tmp_path / "x").write_bytes(b"old")
    (tmp_path / "y").write_bytes(b"old-y")
    baseline = _snapshot_fixture({"x": b"old", "y": b"old-y"})
    candidate = _snapshot_fixture({"x": b"new", "y": b"new-y"})
    evidence = type(
        "Evidence", (),
        {"accepted": True, "fingerprint": candidate.fingerprint}
    )()

    real = broker._write_snapshot_atomically
    calls = []

    def fail_second_candidate_write(target, data):
        calls.append((target.name, data))
        if len(calls) == 2:
            raise OSError("candidate y write failed")
        return real(target, data)

    monkeypatch.setattr(
        broker, "_write_snapshot_atomically", fail_second_candidate_write
    )

    with pytest.raises(OSError, match="candidate y write failed"):
        broker.promote_snapshot(
            tmp_path, baseline, candidate, evidence, candidate.files
        )

    assert calls[0] == ("x", b"new")
    assert calls[1] == ("y", b"new-y")
    assert calls[2] == ("x", b"old")
    assert len(calls) == 3
    assert (tmp_path / "x").read_bytes() == b"old"
    assert (tmp_path / "y").read_bytes() == b"old-y"


def test_snapshot_recovery_refuses_to_overwrite_concurrent_human_edit(tmp_path, monkeypatch):
    import json
    import sophyane.rsi_host_broker as broker

    (tmp_path / "x").write_bytes(b"old")
    (tmp_path / "y").write_bytes(b"old-y")
    baseline = _snapshot_fixture({"x": b"old", "y": b"old-y"})
    candidate = _snapshot_fixture({"x": b"new", "y": b"new-y"})
    evidence = type(
        "Evidence", (),
        {"accepted": True, "fingerprint": candidate.fingerprint}
    )()

    real = broker._write_snapshot_atomically
    calls = [0]

    def fail_after_human_edit(target, data):
        calls[0] += 1
        if calls[0] == 2:
            # x was successfully written by the transaction. Simulate a human
            # changing it before recovery begins, then fail y's candidate write.
            (tmp_path / "x").write_bytes(b"human")
            raise OSError("candidate y write failed")
        return real(target, data)

    monkeypatch.setattr(broker, "_write_snapshot_atomically", fail_after_human_edit)

    with pytest.raises(broker.SnapshotRecoveryError) as error:
        broker.promote_snapshot(
            tmp_path, baseline, candidate, evidence, candidate.files
        )

    assert (tmp_path / "x").read_bytes() == b"human"
    assert (tmp_path / "y").read_bytes() == b"old-y"
    assert error.value.evidence_path.is_file()
    payload = json.loads(error.value.evidence_path.read_text())
    assert payload["repository"] == str(tmp_path)
    assert str(tmp_path / "x") in payload["states"]
    error.value.evidence_path.unlink()


def test_broker_live_candidate_mutation_after_verification_fails_before_primary_write(
        tmp_path, monkeypatch):
    import sophyane.rsi_host_broker as broker
    from sophyane.rsi.candidate_workspace import snapshot

    repository = tmp_path / "repository"
    candidate_source = tmp_path / "candidate"
    repository.mkdir()
    candidate_source.mkdir()

    primary = repository / "value.txt"
    candidate_file = candidate_source / "value.txt"

    primary.write_bytes(b"old")
    candidate_file.write_bytes(b"verified")

    baseline = snapshot(repository)
    independently_verified = snapshot(candidate_source)
    evidence = type(
        "Evidence", (),
        {"accepted": True, "fingerprint": independently_verified.fingerprint}
    )()

    # Verification is complete. The live candidate then changes before
    # the broker acquires its trusted promotion snapshot.
    candidate_file.write_bytes(b"mutated-after-verification")

    writes = []
    real_write = broker._write_snapshot_atomically

    def observe_primary_write(target, data):
        writes.append((target, data))
        return real_write(target, data)

    monkeypatch.setattr(
        broker, "_write_snapshot_atomically", observe_primary_write
    )

    with pytest.raises(PermissionError):
        broker.promote_snapshot(
            repository,
            baseline,
            None,
            evidence,
            {"value.txt"},
            candidate_source=candidate_source,
        )

    assert writes == []
    assert primary.read_bytes() == b"old"
