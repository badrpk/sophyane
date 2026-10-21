import json

from sophyane.core_controller.curriculum_bridge import ObservationCurriculumBridge
from sophyane.core_controller.curriculum_review import CurriculumTaskReviewer
from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource


def _seed(path):
    bridge = ObservationCurriculumBridge(path)
    observation = ImprovementObservation(ImprovementSource.RUNTIME, "repair timeout", "gateway", ("timeout",))
    bridge.enqueue_observation(observation)


def test_llm_review_approves_without_executing_task(tmp_path):
    path = tmp_path / "curriculum.json"
    _seed(path)
    reviewer = CurriculumTaskReviewer(path, reviewer=lambda prompt: '{"action":"approve"}')

    result = reviewer.review()

    assert result["approved"] is True
    state = json.loads(path.read_text())
    assert state["queue"][0]["status"] == "queued"
    assert state["queue"][0]["review_status"] == "approved"


def test_llm_review_rejection_is_durable(tmp_path):
    path = tmp_path / "curriculum.json"
    _seed(path)
    reviewer = CurriculumTaskReviewer(path, reviewer=lambda prompt: '{"action":"reject","reason":"insufficient evidence"}')

    result = reviewer.review()

    assert result["approved"] is False
    state = json.loads(path.read_text())
    assert state["queue"][0]["status"] == "rejected"
    assert state["queue"][0]["failure_reason"] == "insufficient evidence"


def test_pending_review_task_cannot_be_selected(tmp_path):
    path = tmp_path / "curriculum.json"
    _seed(path)
    reviewer = CurriculumTaskReviewer(path, reviewer=lambda prompt: '{"action":"approve"}')
    task_id = reviewer.store.load().queue[0].task_id
    assert reviewer.scheduler.next_task() is None
    reviewer.review(task_id)
    assert reviewer.scheduler.next_task() is not None
