"""Deterministic metric comparison; provider opinions are not evidence."""
from math import isfinite
from .models import PromotionDecision
from .weakness import detect


def compare(weakness, baseline_metrics, candidate_metrics):
    reasons = []
    if detect(weakness) is None:
        return PromotionDecision(False, ('No measurable weakness',))
    try:
        target = weakness.target_metric
        if not isfinite(baseline_metrics[target]) or not isfinite(candidate_metrics[target]):
            raise ValueError('Nonfinite measurement')
        for name in weakness.protected_metrics:
            if name != target and (not isfinite(baseline_metrics[name]) or not isfinite(candidate_metrics[name])):
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
