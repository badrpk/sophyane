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
