import json
from pathlib import Path

from sophyane.evolution.evidence_pipeline import (
    AnalysisPipeline,
    EvidenceStore,
    deterministic_analysis,
)


def _failed_record(
    capability: str = "filesystem",
) -> dict:
    return {
        "task": {
            "task_id": "task-one",
            "capability": capability,
            "prompt": "Create an exact file.",
        },
        "trace": {
            "exit_code": 0,
            "stdout": "completed",
            "stderr": "",
            "files": [],
        },
        "validation": {
            "passed": False,
            "checks": {
                "file_exists": False,
                "exact_bytes": False,
            },
            "errors": [
                "file_exists",
                "exact_bytes",
            ],
        },
        "status": "failure_observed",
    }


def test_store_always_initializes_principles(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path)

    assert store.principles.path.is_file()


def test_deterministic_analysis_works_without_models() -> None:
    report = deterministic_analysis(
        _failed_record()
    )

    assert report.suspected_component == "filesystem"
    assert report.general_principle
    assert report.confidence >= 0.65


def test_failed_record_can_be_synthesized_offline(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path)

    path = (
        store.records
        / "record.json"
    )

    path.write_text(
        json.dumps(
            _failed_record()
        ),
        encoding="utf-8",
    )

    pipeline = AnalysisPipeline(tmp_path)

    result = pipeline.analyze_path(
        path,
        use_local=False,
        use_cloud=False,
    )

    analysis = result["analysis_pipeline"]

    assert analysis["deterministic"]
    assert analysis["blind"] is None
    assert analysis["cloud"] is None
    assert analysis["principle"] is not None
    assert result["status"] == "principle_candidate"


def test_same_offline_principle_becomes_recurrent(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path)

    for index in (1, 2):
        record = _failed_record()
        record["task"]["task_id"] = (
            f"task-{index}"
        )

        path = (
            store.records
            / f"record-{index}.json"
        )

        path.write_text(
            json.dumps(record),
            encoding="utf-8",
        )

    pipeline = AnalysisPipeline(tmp_path)

    pipeline.analyze_pending(
        use_local=False,
        use_cloud=False,
    )

    recurrent = (
        store.principles
        .recurrent_principles(
            component="filesystem"
        )
    )

    assert len(recurrent) == 1
    assert (
        len(
            recurrent[0][
                "distinct_tasks"
            ]
        )
        == 2
    )


def test_cloud_cannot_move_filesystem_failure_to_semantic_router(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.models import FeedbackReport

    deterministic = deterministic_analysis(
        _failed_record("filesystem")
    )

    cloud = FeedbackReport(
        kind="hindsight",
        author="gemini",
        summary="The request was misrouted.",
        evidence=["index.html was attempted"],
        suspected_component="semantic_router",
        confidence=0.95,
        mismatch=(
            "The requested file was not written because another "
            "route intercepted execution."
        ),
        general_principle=(
            "Accurate semantic interpretation must precede execution."
        ),
    )

    final, arbitration = (
        AnalysisPipeline._select_final(
            capability="filesystem",
            deterministic=deterministic,
            blind=None,
            cloud=cloud,
        )
    )

    assert final.suspected_component == "filesystem"
    assert arbitration["cloud_accepted"] is False
    assert (
        arbitration["decision"]
        == "deterministic_component_guard"
    )
    assert arbitration["disagreement"]


def test_grounded_cloud_analysis_is_accepted(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.models import FeedbackReport

    deterministic = deterministic_analysis(
        _failed_record("filesystem")
    )

    cloud = FeedbackReport(
        kind="hindsight",
        author="gemini",
        summary=(
            "The filesystem executor did not create the requested artifact."
        ),
        evidence=["file_exists=False"],
        suspected_component="filesystem",
        confidence=0.91,
        mismatch=(
            "The actor believed execution completed, but no file existed."
        ),
        general_principle=(
            "Filesystem completion must be based on verified workspace "
            "effects rather than process completion alone."
        ),
    )

    final, arbitration = (
        AnalysisPipeline._select_final(
            capability="filesystem",
            deterministic=deterministic,
            blind=None,
            cloud=cloud,
        )
    )

    assert final is cloud
    assert final.suspected_component == "filesystem"
    assert arbitration["cloud_accepted"] is True
    assert arbitration["decision"] == "cloud_grounded"


def test_missing_cloud_uses_deterministic_analysis() -> None:
    deterministic = deterministic_analysis(
        _failed_record("python")
    )

    final, arbitration = (
        AnalysisPipeline._select_final(
            capability="python",
            deterministic=deterministic,
            blind=None,
            cloud=None,
        )
    )

    assert final is deterministic
    assert final.suspected_component == "python"
    assert (
        arbitration["decision"]
        == "deterministic_cloud_unavailable"
    )


def test_explicit_analysis_consumes_verified_history_once(monkeypatch, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    rows = []
    for index in (1, 2):
        record = _failed_record()
        record["task"]["task_id"] = f"analysis-{index}"
        path = store.records / f"analysis-{index}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        rows.append(path)

    calls = []
    evidence = [{
        "event_key": "verified-event", "objective_hash": "objective-hash",
        "original_objective": "verified objective", "accepted": True,
        "status": "succeeded", "verification_state": "verified",
        "verification_evidence": [{"ok": True}],
        "repository_identity": "repo-alpha", "provider_identity": "provider-a",
        "capability_class": "filesystem",
    }]
    original = store.collect_verified_execution_evidence
    def collect(**kwargs):
        calls.append(kwargs)
        return evidence
    monkeypatch.setattr(store, "collect_verified_execution_evidence", collect)
    pipeline = AnalysisPipeline(tmp_path)
    pipeline.store = store
    results = pipeline.analyze_pending(use_local=False, use_cloud=False)
    assert len(results) == 2
    assert len(calls) == 1
    assert results[0]["analysis_pipeline"]["verified_execution_evidence"][0]["event_key"] == "verified-event"
    assert results[1]["analysis_pipeline"]["verified_execution_evidence"][0]["repository_identity"] == "repo-alpha"
    assert original is not None


def test_explicit_verified_history_updates_existing_success_patterns_once(monkeypatch, tmp_path: Path) -> None:
    from sophyane.evolution.evidence_pipeline import EvidenceStore
    rows = [
        {"event_key": "event-1", "objective_hash": "objective-1", "accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "capability_class": "filesystem", "repository_identity": "repo-alpha"},
        {"event_key": "event-2", "objective_hash": "objective-2", "accepted": True, "status": "succeeded", "verification_state": "verified", "verification_evidence": [{"ok": True}], "capability_class": "filesystem", "repository_identity": "repo-alpha"},
    ]
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: rows)
    store = EvidenceStore(tmp_path)
    pipeline = AnalysisPipeline(tmp_path)
    pipeline.collect_verified_execution_evidence()
    pipeline.collect_verified_execution_evidence()
    pattern = store.principles._load()["success_patterns"]["filesystem@repo-alpha"]
    assert pattern["passes"] == 2
    assert pattern["tasks"] == ["objective-1", "objective-2"]


def _verified_event(key, objective, *, capability="filesystem", repository="repo-alpha"):
    return {
        "event_key": key, "trace_id": "trace-" + key,
        "objective_hash": objective, "original_objective": "verified task " + objective,
        "accepted": True, "status": "succeeded", "verification_state": "verified",
        "verification_evidence": [{"ok": True, "command": ["check"]}],
        "repository_identity": repository, "capability_class": capability,
        "provider_identity": "provider-a",
    }


def test_distinct_verified_events_synthesize_one_scoped_recurrent_principle(monkeypatch, tmp_path: Path):
    from sophyane.evolution.evidence_pipeline import AnalysisPipeline
    rows = [_verified_event("event-1", "objective-1"), _verified_event("event-2", "objective-2")]
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: rows)
    pipeline = AnalysisPipeline(tmp_path)
    pipeline.collect_verified_execution_evidence()
    pipeline.collect_verified_execution_evidence()
    principles = pipeline.store.principles.recurrent_principles(component="filesystem")
    assert len(principles) == 1
    assert principles[0]["status"] == "recurrent"
    assert principles[0]["repository_identity"] == "repo-alpha"
    assert principles[0]["supporting_event_keys"] == ["event-1", "event-2"]


def test_one_or_duplicate_verified_event_cannot_synthesize(monkeypatch, tmp_path: Path):
    from sophyane.evolution.evidence_pipeline import AnalysisPipeline
    row = _verified_event("event-1", "objective-1")
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: [row, dict(row)])
    pipeline = AnalysisPipeline(tmp_path)
    pipeline.collect_verified_execution_evidence()
    assert pipeline.store.principles.recurrent_principles() == []


def test_verified_principles_do_not_cross_repository_or_capability(monkeypatch, tmp_path: Path):
    from sophyane.evolution.evidence_pipeline import AnalysisPipeline
    rows = [_verified_event("a", "oa", repository="repo-a"), _verified_event("b", "ob", repository="repo-b"), _verified_event("c", "oc", capability="python", repository="repo-a")]
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: rows)
    pipeline = AnalysisPipeline(tmp_path)
    pipeline.collect_verified_execution_evidence()
    assert pipeline.store.principles.recurrent_principles() == []


def test_verified_principle_identity_is_deterministic(monkeypatch, tmp_path: Path):
    from sophyane.evolution.evidence_pipeline import AnalysisPipeline
    rows = [_verified_event("event-1", "objective-1"), _verified_event("event-2", "objective-2")]
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: rows)
    first = AnalysisPipeline(tmp_path / "one")
    second = AnalysisPipeline(tmp_path / "two")
    first.collect_verified_execution_evidence()
    second.collect_verified_execution_evidence()
    assert first.store.principles.recurrent_principles()[0]["id"] == second.store.principles.recurrent_principles()[0]["id"]
