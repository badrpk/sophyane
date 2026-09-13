"""Deterministic metric comparison; provider opinions are not evidence."""
from math import isfinite
from .models import PromotionDecision
from .weakness import detect


def compare(weakness, baseline_metrics, candidate_metrics):
    reasons = []
    if detect(weakness) is None:
        return PromotionDecision(False, ('No measurable weakness',))
    try:
        names = {weakness.target_metric, *weakness.protected_metrics}
        if any(not isfinite(values[name]) for values in (baseline_metrics, candidate_metrics) for name in names):
            raise ValueError('Nonfinite measurement')
        sign = 1 if weakness.direction == 'higher' else -1
        improvement = sign * (candidate_metrics[weakness.target_metric] - baseline_metrics[weakness.target_metric])
        if improvement < weakness.required_improvement:
            reasons.append('Target improvement below required threshold')
        for name, policy in weakness.protected_metrics.items():
            tolerance = policy['tolerance']
            if not isfinite(tolerance) or tolerance < 0 or policy['direction'] not in ('higher', 'lower'):
                raise ValueError('Invalid protected metric policy')
            sign = 1 if policy['direction'] == 'higher' else -1
            if sign * (candidate_metrics[name] - baseline_metrics[name]) < -tolerance:
                reasons.append(f'Protected metric regressed: {name}')
    except (KeyError, TypeError, ValueError):
        reasons.append('Missing or invalid metric evidence')
    return PromotionDecision(not reasons, tuple(reasons), {'baseline_metrics': baseline_metrics,
                                                         'candidate_metrics': candidate_metrics})
