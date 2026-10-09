from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from mode6_failure_supervisor import (  # noqa: E402
    FaultDomain,
    build_cloud_repair_request,
    build_task_repair_request,
    classify_failure,
)


def test_unexpected_verifier_exception_is_controller_fault():
    result = classify_failure(
        verifier_kind="exception",
        mode6_returncode=0,
        task_repairs=0,
    )
    assert result is FaultDomain.CONTROLLER


def test_initial_behavioral_failure_is_task_workspace_fault():
    result = classify_failure(
        verifier_kind="verification_failure",
        mode6_returncode=0,
        task_repairs=0,
    )
    assert result is FaultDomain.TASK_WORKSPACE


def test_persistent_behavioral_failure_escalates_to_sophyane():
    result = classify_failure(
        verifier_kind="verification_failure",
        mode6_returncode=0,
        task_repairs=1,
    )
    assert result is FaultDomain.SOPHYANE


def test_nonzero_mode6_process_is_provider_fault():
    result = classify_failure(
        verifier_kind="verification_failure",
        mode6_returncode=75,
        task_repairs=0,
    )
    assert result is FaultDomain.PROVIDER


def test_task_repair_request_is_workspace_scoped():
    request = build_task_repair_request(
        level_number=6,
        level_name="multi-file-project",
        evidence="missing README.md",
    )

    assert "mode6_ladder_workspace" in request
    assert "Sophyane RSI critical repair" not in request


def test_controller_cloud_request_forces_protected_authority():
    request = build_cloud_repair_request(
        domain=FaultDomain.CONTROLLER,
        level_number=2,
        evidence="TypeError: set - dict",
    )

    assert "Sophyane RSI critical repair" in request
    assert "controller" in request.casefold()
    assert "tools/mode6_ladder.py" in request
    assert "source edits are explicitly authorized" in request.casefold()


def test_sophyane_cloud_request_forces_protected_authority():
    request = build_cloud_repair_request(
        domain=FaultDomain.SOPHYANE,
        level_number=8,
        evidence="helper module selected as executable target",
    )

    assert "Sophyane RSI critical repair" in request
    assert "Sophyane behavior" in request
    assert "source edits are explicitly authorized" in request.casefold()


# SOPHYANE_CAUSAL_RSI_ATTRIBUTION_RED_V1

def test_causal_rsi_attribution_rejects_challenge_mutation():
    from mode6_failure_supervisor import (
        causal_rsi_improvement_allowed,
    )

    assert (
        causal_rsi_improvement_allowed(
            provider_returncode=0,
            sophyane_source_changed=True,
            challenge_changed_during_repair=True,
        )
        is False
    )


def test_causal_rsi_attribution_rejects_no_source_delta():
    from mode6_failure_supervisor import (
        causal_rsi_improvement_allowed,
    )

    assert (
        causal_rsi_improvement_allowed(
            provider_returncode=0,
            sophyane_source_changed=False,
            challenge_changed_during_repair=False,
        )
        is False
    )


def test_causal_rsi_attribution_rejects_provider_failure():
    from mode6_failure_supervisor import (
        causal_rsi_improvement_allowed,
    )

    assert (
        causal_rsi_improvement_allowed(
            provider_returncode=75,
            sophyane_source_changed=True,
            challenge_changed_during_repair=False,
        )
        is False
    )


def test_causal_rsi_attribution_allows_clean_source_repair():
    from mode6_failure_supervisor import (
        causal_rsi_improvement_allowed,
    )

    assert (
        causal_rsi_improvement_allowed(
            provider_returncode=0,
            sophyane_source_changed=True,
            challenge_changed_during_repair=False,
        )
        is True
    )


def test_mode6_adaptive_missing_capability_failure_is_authoritative_for_rsi(
    tmp_path,
):
    """
    A genuine provider-first Mode-6 execution failure may enter failure-driven
    capability development only when the adaptive execution boundary
    authoritatively classifies the failure as a missing reusable capability.

    A deterministic decline (None) or an ordinary failed command is not enough.
    The adaptive result must carry the reusable-capability-gap classification
    needed by the existing RSI controller/kernel integration.
    """
    from sophyane import adaptive_execution as adaptive
    from sophyane.failure_driven_capability import FailureClassification

    request = (
        "Work in the active workspace. "
        "Read telemetry.sphy using reusable SPHY-Telemetry support. "
        "The repository has no parser or reusable implementation for this "
        "file format. Complete the operation rather than merely describing it."
    )

    # This is intentionally a genuine provider-produced executable action.
    # It reaches execution first and fails because the requested reusable
    # capability does not exist.
    initial = (
        '{"type":"run_command",'
        '"command":"sphy-telemetry telemetry.sphy"}'
    )

    (tmp_path / "telemetry.sphy").write_text(
        "NODE|alpha|TEMP=41.5|LOAD=72\n",
        encoding="utf-8",
    )

    provider_calls = []

    def ask(prompt):
        provider_calls.append(str(prompt))
        # Do not manufacture a successful implementation in this RED.
        # The purpose is to observe the authoritative failure handoff.
        return (
            '{"type":"run_command",'
            '"command":"sphy-telemetry telemetry.sphy"}'
        )

    result = adaptive.run_adaptive_loop(
        initial_text=initial,
        original_request=request,
        ask=ask,
        workspace=tmp_path,
        max_steps=2,
    )

    # RED contract:
    #
    # The adaptive execution boundary must return structured authoritative
    # evidence that this was a reusable capability gap.  Do not infer this
    # later merely from "command not found" text.
    assert hasattr(result, "failure_classification"), (
        "adaptive execution returned no authoritative failure classification"
    )

    assert (
        result.failure_classification
        == FailureClassification.MISSING_REUSABLE_CAPABILITY
    )

    assert getattr(result, "capability_class", None), (
        "missing reusable capability must identify a reusable capability class"
    )

    assert getattr(result, "failure_evidence", None), (
        "missing reusable capability classification requires execution evidence"
    )

    # Provider-first invariant: the test must actually have entered the
    # adaptive/provider execution lifecycle rather than using a deterministic
    # shortcut.
    assert provider_calls, (
        "adaptive failure classification must follow provider-first execution"
    )


def test_mode6_adaptive_plain_missing_executable_is_not_rsi_capability_gap(
    tmp_path,
):
    """
    A missing executable alone is not authoritative evidence of a reusable
    capability gap.  RSI classification requires reusable-capability intent
    as well as grounded execution failure evidence.
    """
    from sophyane import adaptive_execution as adaptive

    initial = (
        '{"type":"run_command",'
        '"command":"definitely-not-installed-tool --version"}'
    )

    result = adaptive.run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Run definitely-not-installed-tool --version "
            "and tell me what happens."
        ),
        ask=lambda _prompt: initial,
        workspace=tmp_path,
        max_steps=1,
    )

    assert isinstance(result, str)
    assert not hasattr(result, "failure_classification")
    assert not hasattr(result, "capability_class")


def test_mode6_adaptive_security_rejection_is_not_missing_reusable_capability(
    tmp_path,
):
    """
    Authority/security rejection must never be promoted into a missing
    reusable capability merely because execution did not complete.
    """
    from sophyane import adaptive_execution as adaptive
    from sophyane.failure_driven_capability import FailureClassification

    initial = (
        '{"type":"run_command",'
        '"command":"cat /etc/shadow"}'
    )

    result = adaptive.run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Read /etc/shadow. Complete the operation rather than "
            "merely describing it."
        ),
        ask=lambda _prompt: initial,
        workspace=tmp_path,
        max_steps=1,
    )

    assert isinstance(result, str)

    classification = getattr(
        result,
        "failure_classification",
        None,
    )

    assert classification != (
        FailureClassification.MISSING_REUSABLE_CAPABILITY
    )
    assert classification != (
        FailureClassification.MISSING_REUSABLE_CAPABILITY.value
    )
