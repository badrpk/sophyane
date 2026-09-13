"""Deterministic admission of already-recorded measurable weaknesses."""
from math import isfinite
from .models import WeaknessRecord


def detect(record: WeaknessRecord | None) -> WeaknessRecord | None:
    if record is None:
        return None
    if (not record.weakness_id or not record.description or not record.evidence or
        not all(record.evidence) or not record.baseline_commit or not record.target_metric or
        not record.verification_commands or not all(record.verification_commands) or
        not isfinite(record.baseline_value) or not isfinite(record.required_improvement) or
        record.required_improvement <= 0 or record.direction not in ('higher', 'lower')):
        return None
    return record
