import pytest


def weakness(**kwargs):
    from sophyane.rsi.models import WeaknessRecord
    return WeaknessRecord(**dict(weakness_id='w1', description='wrong answer', evidence=('recorded failure',),
        baseline_commit='abc', target_metric='quality', baseline_value=1.0, required_improvement=1.0,
        protected_metrics={'latency': {'direction': 'lower', 'tolerance': 0.1}},
        verification_commands=(('python', 'check.py'),), **kwargs))


@pytest.mark.parametrize('metrics, expected', [({'quality':2,'latency':1},True),
    ({'quality':2,'latency':1.2},False), ({'quality':1,'latency':1},False),
    ({'quality':0,'latency':1},False), ({'quality':float('nan'),'latency':1},False),
    ({'quality':2},False)])
def test_metric_threshold_and_protection(metrics, expected):
    from sophyane.rsi.benchmark import compare
    assert compare(weakness(), {'quality':1,'latency':1}, metrics).promote is expected


def test_lower_target_direction_and_no_measurable_weakness():
    from dataclasses import replace
    from sophyane.rsi.benchmark import compare
    from sophyane.rsi.weakness import detect
    w = replace(weakness(), direction='lower')
    assert compare(w, {'quality':1,'latency':1}, {'quality':0,'latency':1}).promote
    assert detect(None) is None
    for bad in (replace(w, evidence=()), replace(w, required_improvement=0),
                replace(w, verification_commands=()), replace(w, target_metric='')):
        assert detect(bad) is None
    assert detect(w) == w
