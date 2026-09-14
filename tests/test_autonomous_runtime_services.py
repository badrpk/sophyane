from sophyane.rsi import supervisor


def test_default_controller_wires_read_only_local_and_targeted_research(tmp_path):
    controller = supervisor.default_controller(tmp_path)
    assert set(controller.local.models) == {'qwen', 'spark'}
    assert controller.research is not None
    assert tuple(controller.cloud.reviewers) == ('codex_cli', 'nifdu_browser')
    assert controller.workspace_factory is not None


def test_default_runtime_persists_structured_stage_and_metric_evidence(tmp_path):
    import json
    from sophyane.rsi.observation_bus import autonomous_bus, ImprovementObservation, ImprovementSource
    autonomous_bus.drain(256)
    autonomous_bus.submit(ImprovementObservation(ImprovementSource.DIAGNOSTIC, 'failure', 'engine', ('trace',)))
    controller = supervisor.default_controller(tmp_path)
    with supervisor.foreground_work():
        controller.tick()
    path = tmp_path / 'stages.jsonl'
    assert path.exists()
    assert json.loads(path.read_text().splitlines()[-1])['stage'] == 'OBSERVE'
    assert json.loads((tmp_path / 'metrics.json').read_text())['counters']['observations'] == 1


def test_host_policy_cannot_allow_benchmark_mutation(tmp_path):
    import json
    import pytest
    spec = {'engine': {'identifier': 'bug', 'version': '1',
        'focused': [['pytest', 'focused']], 'holdout': [['pytest', 'holdout']],
        'regression': [['pytest', 'regression']], 'expected_failure': 'wrong',
        'allowed_paths': ['benchmark.py'], 'benchmark_command': ['python', 'benchmark.py'],
        'meta_command': ['python', 'meta.py']}}
    (tmp_path / 'experiments.json').write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        supervisor.default_controller(tmp_path)
