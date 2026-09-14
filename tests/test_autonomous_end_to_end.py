from pathlib import Path
import pytest
from sophyane.rsi.autonomous import AutonomousRSIController
from sophyane.rsi.observation_bus import ObservationBus, ImprovementObservation, ImprovementSource
from sophyane.rsi.weakness_ledger import WeaknessLedger
from sophyane.rsi.resource_governor import ResourceGovernor, ResourceSnapshot
from sophyane.rsi.candidate_workspace import CandidateWorkspace
from sophyane.rsi.experiment import ExperimentPlan, DeterministicExperimentRunner
from sophyane.rsi.local_intelligence import LocalIntelligenceRouter
from sophyane.rsi.cloud_review import CloudReviewer
from sophyane.rsi.models import CommandResult


def build(tmp_path, *, cloud_patch=None, holdout_fail=False, available=True, gain=True):
    repo = tmp_path / 'repo'; repo.mkdir(); (repo / 'engine.py').write_text('bad')
    bus, ledger = ObservationBus(), WeaknessLedger()
    bus.submit(ImprovementObservation(ImprovementSource.TEST, 'wrong answer', 'engine', ('assertion trace',)))
    resources = ResourceSnapshot(user_active=False, online=True, cloud_budget_available=True,
                                 codex_available=available, qwen_available=True)
    plan = ExperimentPlan('bug', (('pytest', 'focused'),), (('pytest', 'holdout'),),
                          (('pytest', 'regression'),), 'wrong answer', frozenset({'engine.py'}))
    def check(argv, path, **kw):
        good = (path / 'engine.py').read_text() == 'good' and not (holdout_fail and 'holdout' in argv)
        return CommandResult(argv, 0 if good else 1, 'AssertionError: wrong answer', str(path))
    cloud = CloudReviewer({'codex_cli': lambda package: {'action': 'improve' if cloud_patch else 'approve',
                                                        'files': cloud_patch or {}, 'tests_passed': True}})
    controller = AutonomousRSIController(bus, ledger, ResourceGovernor(sampler=lambda: resources),
        local=LocalIntelligenceRouter({'qwen': lambda context, role: 'inspect engine'}), plans={'engine': plan},
        workspace_factory=lambda: CandidateWorkspace(repo, tmp_path / 'scratch').create(),
        prepare=lambda candidate, plan, hypotheses: candidate.apply('codex_cli', {'engine.py': 'good'}, plan.allowed_paths),
        runner=DeterministicExperimentRunner(check), cloud=cloud,
        measure=lambda path: {'benchmark_success': float(gain and (path / 'engine.py').read_text() == 'good')},
        meta_measure=lambda: {'diagnosis_success': 1.0})
    return controller, repo


def test_full_pipeline_promotes_only_after_reverification_and_measurement(tmp_path):
    controller, repo = build(tmp_path)
    for _ in range(18):
        controller.tick()
    assert (repo / 'engine.py').read_text() == 'good'
    stages = [r['stage'] for r in controller.state.records]
    expected = ['OBSERVE', 'PRIORITIZE', 'LOCAL_ANALYSIS', 'EXPERIMENT', 'RED', 'CANDIDATE',
                'PREVERIFY', 'CLOUD_REVIEW', 'AUTHORIZED_IMPLEMENTATION', 'REVERIFY', 'PROMOTE',
                'MEASURE', 'META_MEASURE', 'RECORD']
    assert stages[:14] == expected
    assert controller.metrics.counters['accepted_candidates'] == 1
    assert controller.metrics.level < 4
    assert controller.accepted_baseline is not None


@pytest.mark.parametrize('kwargs', [dict(holdout_fail=True), dict(available=False), dict(gain=False),
                                    dict(cloud_patch={'engine.py': 'broken'}),
                                    dict(cloud_patch={'src/sophyane/intelligence_authority.py': 'allow all'})])
def test_failed_gate_never_promotes(tmp_path, kwargs):
    controller, repo = build(tmp_path, **kwargs)
    for _ in range(18):
        controller.tick()
    assert (repo / 'engine.py').read_text() == 'bad'
    assert controller.accepted_baseline is None
    assert 'PROMOTE' not in [r['stage'] for r in controller.state.records]


def test_concurrent_primary_edit_prevents_promotion(tmp_path):
    controller, repo = build(tmp_path)
    for _ in range(10):
        controller.tick()
    assert controller.state.stage == 'PROMOTE'
    (repo / 'engine.py').write_text('legitimate new edit')
    controller.tick()
    assert (repo / 'engine.py').read_text() == 'legitimate new edit'
    assert controller.accepted_baseline is None


def test_duplicate_candidate_backs_off(tmp_path):
    controller, repo = build(tmp_path)
    for _ in range(5):
        controller.tick()
    controller.prepare(controller.candidate, controller.plan, controller.hypotheses)
    controller.seen.add(controller.candidate.diff().fingerprint)
    controller.tick()
    assert any('duplicate' in reason for r in controller.ledger.records.values() for reason in r.rejection_history)
    assert (repo / 'engine.py').read_text() == 'bad'


def test_post_promotion_measurement_failure_cannot_leave_unaccepted_patch(tmp_path):
    controller, repo = build(tmp_path)
    for _ in range(11):
        controller.tick()
    assert (repo / 'engine.py').read_text() == 'good'
    controller.measure = lambda path: {'benchmark_success': 0}
    controller.tick()
    assert (repo / 'engine.py').read_text() == 'bad'
    assert controller.accepted_baseline is None


def test_patch_swapped_after_cloud_review_is_not_authorized(tmp_path):
    controller, repo = build(tmp_path)
    for _ in range(8):
        controller.tick()
    assert controller.state.stage == 'AUTHORIZED_IMPLEMENTATION'
    (controller.candidate.path / 'engine.py').write_text('good\n# swapped after review')
    controller.tick()
    assert controller.state.stage == 'OBSERVE'
    assert (repo / 'engine.py').read_text() == 'bad'


def test_meta_degradation_blocks_promotion_even_with_capability_gain(tmp_path):
    controller, repo = build(tmp_path)
    measurements = iter((1.0, .2, .2))
    controller.meta_measure = lambda: {'diagnosis_success': next(measurements)}
    for _ in range(18):
        controller.tick()
    assert (repo / 'engine.py').read_text() == 'bad'
    assert any('meta degradation' in reason for r in controller.ledger.records.values() for reason in r.rejection_history)
