"""Host-measured trends and operational counts; machinery is not Level 4."""
from dataclasses import dataclass, field
import math

OPERATIONAL = ('observations', 'deduplicated_weaknesses', 'qwen_calls', 'spark_calls', 'frontier_calls',
    'proposal_attempts', 'proposal_accepts', 'proposal_rejections', 'proposal_latency_ms_total',
    'proposal_latency_ms_max',
    'sli_calls', 'experiments', 'confirmed_reds', 'locally_rejected_candidates',
    'cloud_reviews', 'local_reviews', 'codex_reviews', 'nifdu_reviews', 'accepted_candidates',
    'regressions_prevented')
CAPABILITY = ('benchmark_success', 'confirmed_weakness_resolution', 'regression_rate', 'accepted_candidate_quality')
META = ('diagnosis_success', 'genuine_red_rate', 'red_green_conversion',
    'attempts_per_accepted_improvement', 'bad_candidate_rejection_rate',
    'cloud_escalations_per_accepted_improvement', 'cloud_token_cost_per_accepted_improvement',
    'time_to_confirmed_weakness', 'time_to_accepted_improvement')

@dataclass
class RSIMetrics:
    counters: dict = field(default_factory=lambda: dict.fromkeys(OPERATIONAL, 0))
    measurements: list = field(default_factory=list)

    def record_proposal(self, provider: str, accepted: bool, latency_ms: float) -> None:
        """Record host-observed proposal throughput and latency."""
        if not isinstance(latency_ms, (int, float)) or not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("proposal latency must be finite and non-negative")
        self.increment("proposal_attempts")
        self.increment("proposal_accepts" if accepted else "proposal_rejections")
        self.increment(f"{provider}_proposal_attempts")
        self.counters['proposal_latency_ms_total'] += latency_ms
        self.counters['proposal_latency_ms_max'] = max(self.counters['proposal_latency_ms_max'], latency_ms)

    def increment(self, name, amount=1):
        if amount < 0:
            raise ValueError('Counters are monotonic')
        self.counters[name] = self.counters.get(name, 0) + amount

    def record(self, version, capability, meta, accepted):
        if not version or not capability or not meta:
            raise ValueError('Versioned host measurements required')
        if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
               for x in (*capability.values(), *meta.values())):
            raise ValueError('Finite numeric measurements required')
        self.measurements.append(dict(version=version, capability=dict(capability), meta=dict(meta), accepted=accepted is True))
        self.measurements[:] = self.measurements[-256:]

    @property
    def accepted_baseline(self):
        return next((m for m in reversed(self.measurements) if m['accepted']), None)

    @property
    def level(self):
        accepted = [m for m in self.measurements if m['accepted']]
        if not accepted:
            return 0
        if len(accepted) == 1:
            return 1
        recent = accepted[-3:]
        if len(recent) < 3 or len({m['version'] for m in recent}) != 1:
            return 2
        cap = [m['capability'].get('benchmark_success') for m in recent]
        meta = [m['meta'].get('diagnosis_success') for m in recent]
        if any(x is None for x in cap) or not cap[0] < cap[1] < cap[2]:
            return 2
        if any(x is None for x in meta) or not meta[0] < meta[1] < meta[2]:
            return 3
        return 4

    def operational_rates(self):
        accepted = self.counters['accepted_candidates']
        experiments = self.counters['experiments']
        reds = self.counters['confirmed_reds']
        return {
            'genuine_red_rate': reds / experiments if experiments else None,
            'red_green_conversion': accepted / reds if reds else None,
            'attempts_per_accepted_improvement': experiments / accepted if accepted else None,
            'cloud_escalations_per_accepted_improvement': self.counters['cloud_reviews'] / accepted if accepted else None,
            'cloud_token_cost_per_accepted_improvement': None,
        }
