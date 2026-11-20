from sophyane.rsi.metrics import RSIMetrics


def test_record_keeps_exactly_the_newest_256_measurements():
    metrics = RSIMetrics()
    for index in range(300):
        value = float(index)
        metrics.record("v1", {"benchmark_success": value}, {"diagnosis_success": value}, index % 2 == 0)

    assert len(metrics.measurements) == 256
    assert metrics.measurements[0]["capability"]["benchmark_success"] == 44.0
    assert metrics.measurements[-1]["capability"]["benchmark_success"] == 299.0


def test_level_uses_the_three_most_recent_accepted_records():
    metrics = RSIMetrics()
    for index in range(3):
        value = float(index + 1)
        metrics.record("v1", {"benchmark_success": value}, {"diagnosis_success": value}, True)
    metrics.record("v1", {"benchmark_success": 99.0}, {"diagnosis_success": 99.0}, False)

    assert metrics.level == 4
