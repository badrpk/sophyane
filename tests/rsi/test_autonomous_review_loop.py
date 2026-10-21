from pathlib import Path

from sophyane.rsi.curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore, CurriculumTask, ResourceClass, TaskSource
from sophyane.rsi.curriculum_proposals import ProposalResult
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime


def test_continuous_runtime_reviews_pending_task_before_execution(tmp_path: Path):
    task = CurriculumTask("candidate", "ability", "bounded", ("src/example.py",), ("pytest",), TaskSource.LLM_FOLLOW_UP, ResourceClass.LIGHT, review_status="pending")
    store = CurriculumStore(tmp_path / "curriculum.json")
    scheduler = CurriculumScheduler(store, CurriculumPolicy(cooldown_seconds=0))
    scheduler.enqueue(task)

    class Controller:
        calls = []
        def run_task(self, value):
            self.calls.append(value.task_id)
            return {"status": "verified", "evidence": ["passed"]}

    class Intelligence:
        def review(self, _context, proposal):
            return ProposalResult(True, proposal.task, "approved", "codex_cli", ("codex_cli",), "approved")

    controller = Controller()
    runtime = ContinuousCurriculumRuntime(tmp_path, controller, scheduler, enabled=True)
    runtime.intelligence = Intelligence()

    result = runtime.tick()

    assert result["status"] == "verified"
    assert controller.calls == ["candidate"]
