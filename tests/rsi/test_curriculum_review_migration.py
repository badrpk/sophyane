import json

from sophyane.rsi.curriculum import CurriculumStore, TaskStatus


def test_legacy_llm_follow_up_is_migrated_to_pending_review(tmp_path):
    path = tmp_path / "curriculum.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "queue": [{
            "task_id": "legacy-llm",
            "parent_ability_id": "ability",
            "objective": "legacy candidate",
            "editable_paths": ["src/sophyane/"],
            "verification": ["pytest"],
            "source": "llm_follow_up",
            "status": "queued",
        }],
    }))

    task = CurriculumStore(path).load().queue[0]

    assert task.review_status == "pending"
    assert task.status is TaskStatus.QUEUED
