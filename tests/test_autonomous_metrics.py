from sophyane.rsi.metrics import RSIMetrics


def test_meta_level_requires_frozen_version_and_sustained_measured_gain():
    metrics = RSIMetrics()
    for n in range(3):
        metrics.record('frozen-v1', {'benchmark_success': .3 + n/10}, {'diagnosis_success': .3 + n/10}, True)
    assert metrics.level == 4
    metrics.record('frozen-v1', {'benchmark_success': .1}, {'diagnosis_success': .1}, False)
    assert metrics.accepted_baseline['capability']['benchmark_success'] == .5
    metrics.record('different-v2', {'benchmark_success': .9}, {'diagnosis_success': .9}, True)
    assert metrics.level < 4
