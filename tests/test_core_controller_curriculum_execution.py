import json

from sophyane.core_controller.curriculum_bridge import ObservationCurriculumBridge
from sophyane.core_controller.curriculum_review import CurriculumTaskReviewer, execute_approved_host_task
from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource


def _approved(path):
    bridge = ObservationCurriculumBridge(path)
    bridge.enqueue_observation(ImprovementObservation(ImprovementSource.RUNTIME, "check gateway", "provider_gateway", ("evidence",)))
    reviewer = CurriculumTaskReviewer(path, reviewer=lambda _prompt: '{"action":"approve"}')
    reviewer.review()


def test_approved_task_runs_only_declared_regression(tmp_path):
    path = tmp_path / "curriculum.json"
    _approved(path)

    result = execute_approved_host_task(path, runner=lambda command: (0, "tests passed"))

    assert result["status"] == "verified"
    task = json.loads(path.read_text())["queue"][0]
    assert task["status"] == "verified"


def test_pending_task_cannot_execute(tmp_path):
    path = tmp_path / "curriculum.json"
    bridge = ObservationCurriculumBridge(path)
    bridge.enqueue_observation(ImprovementObservation(ImprovementSource.RUNTIME, "check gateway", "provider_gateway", ("evidence",)))

    result = execute_approved_host_task(path, runner=lambda command: (0, "should not run"))

    assert result["status"] == "blocked"
