from sophyane.human_conversation import ImprovementObservation
from sophyane import mode6_rsi_handoff
from sophyane.rsi.observation_bus import ObservationBus


def test_mode6_handoff_automatically_submits_without_mutation(monkeypatch):
    bus = ObservationBus()
    monkeypatch.setattr(mode6_rsi_handoff.ledger, 'propose_improvement', lambda *a, **k: {'ok': True})
    monkeypatch.setattr(mode6_rsi_handoff, 'autonomous_bus', bus, raising=False)
    observation = ImprovementObservation('wrong answer', ('trace',), 'engine', 'reproduce', True)
    result = mode6_rsi_handoff.record_mode6_improvement_observation(observation)
    assert result['recorded']
    pending = bus.drain()
    assert len(pending) == 1
    assert pending[0][0].source.value == 'mode6'
    assert not observation.mutation_authority
