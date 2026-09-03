from __future__ import annotations

import json
import pytest

import sophyane.durable_memory as durable


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _row(key, content, provenance=None, ts=1):
    return {"ts": ts, "memory_key": key, "namespace": "test", "content": content, "metadata": ({"verified_provenance": provenance} if provenance is not None else {})}


def _verified(repo="repo-alpha", capability="capability-a", accepted=True, state="verified"):
    return {"accepted": accepted, "verification_state": state, "repository_identity": repo, "capability_class": capability, "event_key": "event-1"}


def _filesystem_only(monkeypatch):
    monkeypatch.setattr(durable, "_postgres_recall", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))


def test_verified_provenance_is_bounded_ranked_tiebreak(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPHYANE_HOME", str(tmp_path))
    _write(tmp_path / "durable-memory.jsonl", [_row("legacy", "alpha beta", ts=99), _row("verified", "alpha beta", _verified(), ts=1)])
    _filesystem_only(monkeypatch)
    hits = durable.recall("alpha beta", namespace="test", repository_identity="repo-alpha", capability_class="capability-a")
    assert [item["memory_key"] for item in hits] == ["verified", "legacy"]


def test_relevance_remains_primary_and_scope_is_enforced(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPHYANE_HOME", str(tmp_path))
    _write(tmp_path / "durable-memory.jsonl", [_row("strong", "alpha beta gamma", ts=1), _row("weak-verified", "alpha", _verified("repo-alpha"), ts=99), _row("other-repo", "alpha", _verified("repo-beta"), ts=100)])
    _filesystem_only(monkeypatch)
    hits = durable.recall("alpha beta gamma", namespace="test", repository_identity="repo-alpha", capability_class="capability-a")
    assert hits[0]["memory_key"] == "strong"
    assert {item["memory_key"] for item in hits} == {"strong", "weak-verified", "other-repo"}


def test_legacy_and_noncanonical_provenance_are_neutral(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPHYANE_HOME", str(tmp_path))
    _write(tmp_path / "durable-memory.jsonl", [_row("legacy", "alpha", ts=1), _row("failed", "alpha", _verified(accepted=False), ts=2), _row("unverified", "alpha", _verified(state="unverified"), ts=3)])
    _filesystem_only(monkeypatch)
    hits = durable.recall("alpha", namespace="test", repository_identity="repo-alpha", capability_class="capability-a")
    assert [item["memory_key"] for item in hits] == ["unverified", "failed", "legacy"]


def _event(**overrides):
    event = {
        "event_key": "event-verified-1", "objective_hash": "a" * 64,
        "original_objective": "create a generic artifact", "status": "succeeded",
        "verification_state": "verified", "verification_evidence": [{"ok": True}],
        "accepted": True, "repository_identity": "repo-alpha",
        "provider_identity": "provider-a", "capability_class": "artifact",
        "artifact_paths": ["out.txt"], "changed_paths": ["out.txt"],
        "trace_id": "trace-1", "created_at": 1.0,
    }
    event.update(overrides)
    return event


def test_verified_execution_write_is_compact_idempotent_and_retrievable(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPHYANE_HOME", str(tmp_path))
    first = durable.remember_verified_execution(_event())
    second = durable.remember_verified_execution(_event())
    assert first["ok"] is True and second["deduplicated"] is True
    lines = (tmp_path / "durable-memory.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["metadata"]["verified_provenance"]["objective_hash"] == "a" * 64
    assert record["metadata"]["verified_provenance"]["verification_evidence"] == [{"ok": True}]
    _filesystem_only(monkeypatch)
    hits = durable.recall("generic artifact", namespace="verified-execution", repository_identity="repo-alpha", capability_class="artifact")
    assert hits and hits[0]["metadata"]["verified_provenance"]["event_key"] == "event-verified-1"


@pytest.mark.parametrize("overrides", [
    {"accepted": False}, {"verification_state": "failed"}, {"status": "failed"},
    {"verification_evidence": []},
])
def test_untrusted_execution_is_not_written(monkeypatch, tmp_path, overrides):
    monkeypatch.setenv("SOPHYANE_HOME", str(tmp_path))
    result = durable.remember_verified_execution(_event(**overrides))
    assert result["ok"] is False
    assert not (tmp_path / "durable-memory.jsonl").exists()
