from dataclasses import replace
from sophyane.rsi.resource_governor import ResourceSnapshot, ResourceGovernor, ResourceDecision as D


def test_pressure_and_activity_prevent_heavy_work():
    governor = ResourceGovernor()
    idle = ResourceSnapshot(user_active=False, available_ram=8*1024**3, load=0)
    assert governor.decide(replace(idle, user_active=True)) == D.OBSERVE_ONLY
    assert governor.decide(replace(idle, available_ram=10)) == D.OBSERVE_ONLY
    assert governor.decide(replace(idle, battery_percent=5, charging=False)) == D.OBSERVE_ONLY
    assert governor.decide(replace(idle, thermal_state='critical')) == D.OBSERVE_ONLY
    assert governor.decide(idle) == D.LOCAL_LIGHT
    assert governor.decide(replace(idle, spark_available=True)) == D.LOCAL_DEEP
    online = replace(idle, online=True, sli_available=True)
    assert governor.decide(online, research=True) == D.INTERNET_RESEARCH
    assert governor.decide(online, promising=True) != D.CLOUD_REVIEW
    assert governor.decide(replace(online, cloud_budget_available=True, nifdu_available=True), promising=True) == D.CLOUD_REVIEW


def test_scheduler_bounds_fairness_and_retry(tmp_path):
    from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource
    from sophyane.rsi.weakness_ledger import WeaknessLedger
    from sophyane.rsi.opportunity_scheduler import OpportunityScheduler
    ledger = WeaknessLedger()
    for name in ('a', 'b'):
        ledger.ingest(ImprovementObservation(ImprovementSource.TEST, name, 'engine', ('failure',)))
    scheduler = OpportunityScheduler(ledger, ResourceGovernor())
    idle = ResourceSnapshot(user_active=False)
    first = scheduler.select(idle, now=1)
    assert len(first) == 1
    second = scheduler.select(idle, now=2)
    assert first[0].fingerprint != second[0].fingerprint
    ledger.reject(first[0].fingerprint, 'no gain', now=2)
    assert scheduler.select(idle, now=3)[0].fingerprint == second[0].fingerprint
    assert scheduler.select(replace(idle, user_active=True), now=4) == ()
