from dataclasses import replace
from sophyane.rsi.research import TargetedSLIResearch
from sophyane.rsi.resource_governor import ResourceSnapshot
from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource
from sophyane.rsi.weakness_ledger import WeaknessLedger


def test_online_targeted_sli_claims_are_bounded_and_untrusted():
    ledger = WeaknessLedger()
    weakness = ledger.ingest(ImprovementObservation(ImprovementSource.RUNTIME, 'llama memory failure', 'llama', ('trace',)))
    queries = []
    research = TargetedSLIResearch(lambda query, limit: queries.append(query) or [
        {'claim': 'try mmap', 'reference': 'https://example.org/llama'}] * 8, limit=2)
    offline = ResourceSnapshot(user_active=False, sli_available=True)
    assert research.discover(weakness, offline) == () and queries == []
    claims = research.discover(weakness, replace(offline, online=True))
    assert len(claims) == 2
    assert all(not c.trusted and not c.mutation_authority for c in claims)
    assert 'llama memory failure' in queries[0]
    assert claims[0].reference == 'https://example.org/llama'
    assert research.discover(weakness, replace(offline, online=True, user_active=True)) == ()


def test_controller_selects_research_only_for_grounded_online_opportunity():
    from sophyane.rsi.autonomous import AutonomousRSIController
    from sophyane.rsi.observation_bus import ObservationBus
    from sophyane.rsi.resource_governor import ResourceGovernor
    from sophyane.rsi.local_intelligence import LocalIntelligenceRouter
    bus, ledger = ObservationBus(), WeaknessLedger()
    bus.submit(ImprovementObservation(ImprovementSource.RUNTIME, 'llama failure', 'llama', ('trace',)))
    queries = []
    research = TargetedSLIResearch(lambda query, limit: queries.append(query) or [])
    resources = ResourceSnapshot(user_active=False, online=True, sli_available=True, qwen_available=True)
    controller = AutonomousRSIController(bus, ledger, ResourceGovernor(sampler=lambda: resources),
        research=research, local=LocalIntelligenceRouter({'qwen': lambda c, r: 'hypothesis'}))
    for _ in range(5):
        controller.tick()
    assert len(queries) == 1


def test_research_claims_feed_local_reproduction_proposal_but_not_promotion():
    from sophyane.rsi.autonomous import AutonomousRSIController
    from sophyane.rsi.observation_bus import ObservationBus
    from sophyane.rsi.resource_governor import ResourceGovernor
    from sophyane.rsi.local_intelligence import LocalIntelligenceRouter
    seen = []
    bus = ObservationBus()
    bus.submit(ImprovementObservation(ImprovementSource.SLI, 'bad algorithm', 'engine', ('trace',)))
    controller = AutonomousRSIController(bus, WeaknessLedger(), ResourceGovernor(sampler=lambda:
        ResourceSnapshot(user_active=False, online=True, sli_available=True, qwen_available=True)),
        local=LocalIntelligenceRouter({'qwen': lambda context, role: seen.append(context) or 'hypothesis'}),
        research=TargetedSLIResearch(lambda query, limit: [{'claim': 'alternative algorithm', 'reference': 'https://example.org/paper'}]))
    for _ in range(5):
        controller.tick()
    assert any('https://example.org/paper' in context for context in seen)
    assert controller.accepted_baseline is None
