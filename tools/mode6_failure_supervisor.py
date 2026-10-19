"""Failure attribution and bounded repair prompts for the Mode-6 ladder.

The ladder uses this module to keep provider failures, task-workspace
failures, and Sophyane implementation failures causally separate.
"""

from enum import Enum


class FaultDomain(Enum):
    CONTROLLER = "controller"
    TASK_WORKSPACE = "task_workspace"
    SOPHYANE = "sophyane"
    PROVIDER = "provider"


def classify_failure(*, verifier_kind: str, mode6_returncode: int, task_repairs: int) -> FaultDomain:
    if int(mode6_returncode or 0) != 0:
        return FaultDomain.PROVIDER
    if str(verifier_kind).casefold() == "exception":
        return FaultDomain.CONTROLLER
    if int(task_repairs or 0) > 0:
        return FaultDomain.SOPHYANE
    return FaultDomain.TASK_WORKSPACE


def build_task_repair_request(*, level_number: int, level_name: str, evidence: str) -> str:
    return (
        "Repair only the task workspace mode6_ladder_workspace. "
        f"Mode-6 level {level_number} ({level_name}) failed. Evidence: {evidence}. "
        "Do not edit Sophyane source, controller code, or the verifier."
    )


def build_cloud_repair_request(*, domain: FaultDomain, level_number: int, evidence: str) -> str:
    target = {
        FaultDomain.CONTROLLER: "the controller in tools/mode6_ladder.py",
        FaultDomain.SOPHYANE: "Sophyane behavior in the runtime",
    }.get(domain, domain.value)
    return (
        "Sophyane RSI critical repair: "
        f"fault domain is {domain.value}; target {target}; level {level_number}; "
        f"evidence: {evidence}. Source edits are explicitly authorized only "
        "for this diagnosed repair, and the challenge workspace must remain unchanged."
    )


def causal_rsi_improvement_allowed(*, provider_returncode: int, sophyane_source_changed: bool,
                                   challenge_changed_during_repair: bool) -> bool:
    return (
        int(provider_returncode or 0) == 0
        and bool(sophyane_source_changed)
        and not bool(challenge_changed_during_repair)
    )
