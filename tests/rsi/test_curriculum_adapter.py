from types import SimpleNamespace

from sophyane.rsi.curriculum import CurriculumTask, ResourceClass, TaskSource
from sophyane.rsi.curriculum_adapter import (
    AutonomousCurriculumTaskAdapter,
    NativeEvolutionTaskAdapter,
)
from sophyane.rsi.weakness_ledger import WeaknessLedger, WeaknessStatus


def task(**overrides):
    values = dict(
        task_id="task-1",
        parent_ability_id="seed",
        objective="Improve the bounded ability",
        editable_paths=("src/example.py",),
        verification=("pytest", "-q"),
        source=TaskSource.CAPABILITY_GAP,
        resource_class=ResourceClass.LIGHT,
        component="example",
    )
    values.update(overrides)
    return CurriculumTask(**values)


class FakeController:
    def __init__(self, status=WeaknessStatus.ACCEPTED):
        self.ledger = WeaknessLedger()
        self.plans = {"example": SimpleNamespace(allowed_paths=frozenset({"src/example.py"}))}
        self.status = status
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        if self.ledger.records:
            next(iter(self.ledger.records.values())).status = self.status.value


def test_adapter_runs_task_through_controller_and_reports_verified():
    controller = FakeController()

    result = AutonomousCurriculumTaskAdapter(controller, max_cycles=2).run_task(task())

    assert result["status"] == "verified"
    assert result["evidence"]
    assert controller.ticks == 1


def test_adapter_rejects_paths_outside_frozen_plan_without_running():
    controller = FakeController()

    result = AutonomousCurriculumTaskAdapter(controller).run_task(
        task(editable_paths=("src/other.py",))
    )

    assert result["status"] == "rejected"
    assert "allowed" in result["reason"]
    assert controller.ticks == 0


def test_adapter_pauses_when_existing_pipeline_does_not_finish():
    controller = FakeController(status=WeaknessStatus.PENDING)

    result = AutonomousCurriculumTaskAdapter(controller, max_cycles=2).run_task(task())

    assert result["status"] == "paused"
    assert "cycle" in result["reason"]
    assert controller.ticks == 2


def test_native_adapter_reports_native_promotion():
    def factory(config):
        assert config.allow_candidate_patches is True
        assert config.allow_promotion is True
        return SimpleNamespace(run=lambda: [SimpleNamespace(
            run_id="native-1",
            status="candidate_promotable",
            gate=SimpleNamespace(details={"promotion_committed": True}),
        )])

    result = NativeEvolutionTaskAdapter(".", engine_factory=factory).run_task(task())

    assert result["status"] == "verified"
    assert "native_status=candidate_promotable" in result["evidence"][0]
