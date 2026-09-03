from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.durable_memory as durable
import sophyane.sli_learner as learner
import sophyane.unified_execution_kernel as kernel


def test_verified_non_race_capability_uses_canonical_learning_and_durable_fanout(monkeypatch, tmp_path):
    learned = []
    durable_records = []

    def fake_learn(**kwargs):
        learned.append(kwargs)
        event = dict(kwargs["provenance"])
        event["event_key"] = "canonical-event-1"
        return {"provenance": event}

    monkeypatch.setattr(learner, "learn_execution", fake_learn)
    monkeypatch.setattr(durable, "remember_verified_execution", lambda event: durable_records.append(event) or {"ok": True})
    data = {
        "ok": True, "capability": "filesystem.write_exact_verified",
        "relative_path": "artifact.txt", "byte_for_byte_verified": True,
        "runtime_executed_action": True, "deterministic": True,
    }
    monkeypatch.setattr(
        "sophyane.capability_executors.execute_deterministic_capability",
        lambda *_args, **_kwargs: SimpleNamespace(
            ok=True, capability_id="filesystem.write_exact_verified",
            text="VERIFIED", data=data, deterministic=True, provider_bypassed=True,
        ),
    )
    result = kernel.execute_request(
        "write artifact.txt containing verified output",
        workspace=tmp_path,
    )
    assert result is not None and result.ok is True
    assert len(learned) == 1 and len(durable_records) == 1
    provenance = learned[0]["provenance"]
    assert provenance["accepted"] is True
    assert provenance["verification_state"] == "verified"
    assert provenance["capability_class"] == "filesystem.write_exact_verified"
    assert provenance["changed_paths"] == ["artifact.txt"]
    assert durable_records[0]["event_key"] == "canonical-event-1"


def test_non_verified_deterministic_result_does_not_enter_learning(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(learner, "learn_execution", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(
        "sophyane.capability_executors.execute_deterministic_capability",
        lambda *_args, **_kwargs: SimpleNamespace(
            ok=True, capability_id="filesystem.list_folders", text="ok",
            data={"ok": True, "folders": []}, deterministic=True, provider_bypassed=True,
        ),
    )
    result = kernel.execute_request("list folders", workspace=tmp_path)
    assert result is not None and result.ok is True
    assert calls == []
