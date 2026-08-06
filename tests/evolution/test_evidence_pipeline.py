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
