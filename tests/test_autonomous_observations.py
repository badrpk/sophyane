from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource, ObservationBus


def observation(problem='bad result'):
    return ImprovementObservation(ImprovementSource.RUNTIME, problem, 'engine', ('trace',))


def test_bounded_bus_deduplicates_but_retains_occurrences_and_wakes():
    wakes = []
    bus = ObservationBus(capacity=2, wake=lambda: wakes.append(1))
    assert bus.submit(observation())
    assert bus.submit(observation())
    assert bus.submit(observation('other'))
    assert not bus.submit(observation('overflow'))
    values = bus.drain(1)
    assert len(values) == 1 and values[0][1] == 2
    assert len(bus.drain()) == 1
    assert len(wakes) == 3


def test_ledger_persists_occurrences_and_retry_history(tmp_path):
    from sophyane.rsi.weakness_ledger import WeaknessLedger
    path = tmp_path / 'weakness.json'
    ledger = WeaknessLedger(path)
    ledger.ingest(observation(), 2, now=10)
    assert len(ledger.records) == 1
    record = ledger.ingest(observation(), 1, now=11)
    assert record.occurrences == 3
    ledger.reject(record.fingerprint, 'holdout failed', now=12)
    restored = WeaknessLedger(path).records[record.fingerprint]
    assert restored.retry_at > 12
    assert restored.rejection_history == ['holdout failed']
    assert restored.occurrences == 3
