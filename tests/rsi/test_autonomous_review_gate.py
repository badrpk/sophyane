from pathlib import Path

from sophyane.rsi.curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore
from sophyane.rsi.curriculum_proposals import ProposalResult
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime
from sophyane.rsi.curriculum import CurriculumTask, ResourceClass, TaskSource


def test_unreviewed_follow_up_is_queued_but_not_executed(tmp_path: Path):
    task = CurriculumTask("follow-up", "a1", "bounded", ("src/example.py",), ("pytest",), TaskSource.LLM_FOLLOW_UP, ResourceClass.LIGHT)

    class Controller:
        calls = []
        def run_task(self, value):
            self.calls.append(value.task_id)
            return {"status": "verified"}

    class Proposal:
        def propose(self, _context):
            return ProposalResult(True, task, "accepted")

    controller = Controller()
    scheduler = CurriculumScheduler(CurriculumStore(tmp_path / "curriculum.json"), CurriculumPolicy(cooldown_seconds=0))
    runtime = ContinuousCurriculumRuntime(tmp_path, controller, scheduler, proposal_adapter=Proposal(), enabled=True)
    seed = CurriculumTask("seed", "a0", "seed", ("src/example.py",), ("pytest",), TaskSource.CURRICULUM, ResourceClass.LIGHT)
    scheduler.enqueue(seed)
    controller.run_task = lambda value: {"status": "verified"}
    runtime.tick()

    assert scheduler._state().queue[-1].review_status == "pending"
