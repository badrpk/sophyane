from sophyane.rsi.autonomous import AutonomousRSIController
from sophyane.rsi.observation_bus import ObservationBus, ImprovementObservation, ImprovementSource
from sophyane.rsi.weakness_ledger import WeaknessLedger
from sophyane.rsi.resource_governor import ResourceGovernor, ResourceSnapshot


def test_tick_ingests_under_pressure_without_model_calls():
    bus, ledger = ObservationBus(), WeaknessLedger()
    bus.submit(ImprovementObservation(ImprovementSource.RUNTIME, 'crash', 'engine', ('trace',)))
    controller = AutonomousRSIController(bus, ledger, ResourceGovernor(sampler=lambda: ResourceSnapshot(user_active=True)))
    result = controller.tick()
    assert len(ledger.records) == 1
    assert result['decision'] == 'OBSERVE_ONLY'
    assert controller.state.stage == 'OBSERVE'
    assert controller.state.cycles == 1


def test_complete_tick_pipeline_reverifies_cloud_patch_and_preserves_primary_on_failure(tmp_path):
    from sophyane.rsi.candidate_workspace import CandidateWorkspace
    from sophyane.rsi.experiment import ExperimentPlan, DeterministicExperimentRunner
    from sophyane.rsi.local_intelligence import LocalIntelligenceRouter
    from sophyane.rsi.cloud_review import CloudReviewer
    from sophyane.rsi.models import CommandResult
    repo = tmp_path / 'repo'; repo.mkdir(); (repo / 'engine.py').write_text('bad')
    bus, ledger = ObservationBus(), WeaknessLedger()
    bus.submit(ImprovementObservation(ImprovementSource.TEST, 'wrong answer', 'engine', ('assertion trace',)))
    resources = ResourceSnapshot(user_active=False, online=True, cloud_budget_available=True, codex_available=True, qwen_available=True)
    policy = ExperimentPlan('bug', (('pytest', 'focused'),), (('pytest', 'holdout'),),
                            (('pytest', 'regression'),), 'wrong answer', frozenset({'engine.py'}))
    def check(argv, path, **kw):
        text = (path / 'engine.py').read_text()
        return CommandResult(argv, 0 if text == 'good' else 1, 'AssertionError: wrong answer', str(path))
    controller = AutonomousRSIController(bus, ledger, ResourceGovernor(sampler=lambda: resources),
        local=LocalIntelligenceRouter({'qwen': lambda context, role: 'inspect engine'}),
        plans={'engine': policy}, workspace_factory=lambda: CandidateWorkspace(repo, tmp_path / 'scratch').create(),
        prepare=lambda candidate, plan, hypotheses: candidate.apply('codex_cli', {'engine.py': 'good'}, plan.allowed_paths),
        runner=DeterministicExperimentRunner(check),
        cloud=CloudReviewer({'codex_cli': lambda package: {'action': 'improve', 'files': {'engine.py': 'broken'}, 'tests_passed': True}}))
    for _ in range(20):
        controller.tick()
    stages = [r['stage'] for r in controller.state.records]
    assert 'REVERIFY' in stages
    assert 'PROMOTE' not in stages
    assert (repo / 'engine.py').read_text() == 'bad'
    assert any('reverification' in reason for r in ledger.records.values() for reason in r.rejection_history)
