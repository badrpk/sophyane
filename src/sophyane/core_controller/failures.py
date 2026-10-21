"""Stable failure-boundary mapping for controller lifecycle errors."""

from __future__ import annotations

from .models import FailureBoundary


def boundary_for(error: BaseException, *, phase: str) -> FailureBoundary:
    if phase == "selection":
        return FailureBoundary.MODE_UNAVAILABLE
    if phase == "provider":
        return FailureBoundary.PROVIDER_UNAVAILABLE
    if phase == "execution":
        return FailureBoundary.CONTROLLER_INTERNAL
    if phase == "audit":
        return FailureBoundary.STATE_UNAVAILABLE
    return FailureBoundary.CONTROLLER_INTERNAL
