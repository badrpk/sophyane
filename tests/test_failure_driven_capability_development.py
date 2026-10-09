from __future__ import annotations

from dataclasses import dataclass

from sophyane.failure_driven_capability import (
    CapabilityDevelopmentController,
    FailureClassification,
    InMemoryCapabilityStore,
)


@dataclass
class Candidate:
    capability_class: str
    version: int = 1


def _controller(*, verify=lambda candidate, request: True, max_attempts=3):
    calls = []

    def worker(role, context):
        calls.append(role)
        if role == "failure_discovery":
            return {"capability_class": context["capability_class"]}
        if role == "design":
            return {"hypothesis": "add the missing reusable operation"}
        if role == "implementation":
            return Candidate(context["capability_class"])
        if role == "testing":
            return {"tests": ["independent candidate test"]}
        if role == "review":
            return {"approved_for_verification": True}
        raise AssertionError(role)

    return CapabilityDevelopmentController(
        store=InMemoryCapabilityStore(),
        worker=worker,
        verifier=verify,
        max_attempts=max_attempts,
    ), calls


def test_missing_reusable_capability_enters_multiple_stage_graph():
    controller, calls = _controller()

    result = controller.handle_failure(
        request="Convert a report to a structured summary",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
    )

    assert result.accepted is True
    # Promotion succeeded, but this invocation supplied no original
    # executor.  Therefore the failed user operation was not retried.
    assert result.retry_original_request is False
    assert result.evidence["retry_result"] is None
    assert result.trace == [
        "analyze_failure",
        "discover_capability_gap",
        "design_candidate",
        "implement_candidate",
        "test_candidate",
        "review_candidate",
        "verify_candidate",
        "promote_or_reject",
        "retry_original_request",
        "verify_original_outcome",
    ]
    assert calls == ["failure_discovery", "design", "implementation", "testing", "review"]
    assert result.evidence["classification"] == "missing_reusable_capability"
    assert result.evidence["hypotheses"]
    assert result.evidence["test_results"]
    assert result.evidence["review_findings"]
    assert result.evidence["promotion_decision"] == "accepted"


def test_unsuccessful_candidate_repairs_are_bounded_and_preserve_evidence():
    controller, _ = _controller(verify=lambda candidate, request: False, max_attempts=2)

    result = controller.handle_failure(
        request="Convert one document format to another",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
    )

    assert result.accepted is False
    assert result.retry_original_request is False
    assert result.evidence["attempts"] == 2
    assert result.evidence["unresolved_failures"]
    assert result.evidence["promotion_decision"] == "rejected"


def test_security_restriction_never_enters_capability_development():
    controller, calls = _controller()

    result = controller.handle_failure(
        request="Read a protected file",
        failure={"error": "sandbox denied"},
        classification=FailureClassification.SECURITY_AUTHORITY_RESTRICTION,
        capability_class="filesystem.read_protected",
    )

    assert result.accepted is False
    assert result.retry_original_request is False
    assert calls == []
    assert result.evidence["decision"] == "safe_terminal_restriction"


def test_worker_success_without_independent_verification_cannot_promote():
    controller, _ = _controller(verify=lambda candidate, request: False)

    result = controller.handle_failure(
        request="Convert a second report to a structured summary",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
    )

    assert result.accepted is False
    assert controller.store.get("document.transform") is None


def test_verified_capability_is_reused_for_a_different_request():
    controller, calls = _controller()

    first = controller.handle_failure(
        request="Convert report A to a structured summary",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
    )
    second = controller.execute_or_reuse(
        request="Convert report B to a structured summary",
        capability_class="document.transform",
        execute=lambda candidate, request: True,
    )

    assert first.accepted is True
    assert second.reused is True
    assert second.original_outcome_verified is True
    assert calls.count("implementation") == 1


def test_non_capability_failures_do_not_enter_development():
    controller, calls = _controller()

    result = controller.handle_failure(
        request="Call the provider",
        failure={"error": "timeout"},
        classification=FailureClassification.TRANSIENT_PROVIDER_FAILURE,
        capability_class="provider.call",
    )

    assert result.accepted is False
    assert result.evidence["decision"] == "ordinary_failure"
    assert calls == []


def test_infeasible_environment_does_not_enter_development():
    controller, calls = _controller()

    result = controller.handle_failure(
        request="Run an operation requiring unavailable hardware",
        failure={"error": "environment unavailable"},
        classification=FailureClassification.INFEASIBLE_ENVIRONMENTAL_RESTRICTION,
        capability_class="hardware.accelerator",
    )

    assert result.accepted is False
    assert result.evidence["decision"] == "ordinary_failure"
    assert calls == []


def test_unified_execution_failure_can_enter_controller_and_retry(monkeypatch, tmp_path):
    from sophyane import unified_execution_kernel as kernel
    from sophyane.unified_execution_kernel import ExecutionResult

    controller, _ = _controller()
    registry_calls = []

    class Registry:
        def execute(self, request):
            registry_calls.append(request.text)
            now = 1.0
            return ExecutionResult(
                handled=True,
                ok=False,
                capability="development.missing_operation",
                output="unsupported operation",
                evidence={"failure_classification": "missing_reusable_capability"},
                started_at=now,
                finished_at=now,
            )

    monkeypatch.setattr(kernel, "initialize_registry", lambda: Registry())
    config = {
        "controller": controller,
        "classification": "missing_reusable_capability",
        "capability_class": "document.transform",
        "execute": lambda candidate, request: True,
    }
    first = kernel.execute_request(
        "Convert report A to a structured summary",
        workspace=tmp_path,
        metadata={"failure_driven_capability": config},
    )
    second = kernel.execute_request(
        "Convert report B to a structured summary",
        workspace=tmp_path,
        metadata={"failure_driven_capability": config},
    )

    assert first is not None and first.ok is True
    assert "failure_driven_capability" in first.evidence
    assert second is not None and second.ok is True
    assert second.evidence["capability_reuse"]["decision"] == "reused_verified_capability"
    assert len(registry_calls) == 1


def test_verified_candidate_without_original_executor_cannot_claim_retry_success():
    """
    Candidate verification and original-request verification are distinct.

    Promotion may authorize later reuse, but when no original executor was
    supplied this invocation must not claim that the failed user operation
    was successfully retried.
    """
    controller, _ = _controller()

    result = controller.handle_failure(
        request="Convert report A to a structured summary",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
        execute_original=None,
    )

    assert result.accepted is True
    assert result.evidence["promotion_decision"] == "accepted"
    assert result.evidence["retry_result"] is None

    assert result.retry_original_request is False, (
        "controller claimed original-request retry success "
        "without executing the original request"
    )


def test_worker_testing_and_review_claims_cannot_replace_independent_verification():
    """
    The development worker may claim tests/review succeeded, but promotion
    still requires the separately configured verifier.
    """
    calls = []

    def worker(role, context):
        calls.append(role)

        if role == "failure_discovery":
            return {
                "capability_class": context["capability_class"],
            }

        if role == "design":
            return {
                "hypothesis": "implement reusable capability",
            }

        if role == "implementation":
            return Candidate(
                context["capability_class"],
            )

        if role == "testing":
            return {
                "passed": True,
                "claim": "all tests passed",
            }

        if role == "review":
            return {
                "approved_for_verification": True,
                "claim": "candidate approved",
            }

        raise AssertionError(role)

    controller = CapabilityDevelopmentController(
        store=InMemoryCapabilityStore(),
        worker=worker,
        verifier=lambda candidate, request: False,
        max_attempts=1,
    )

    result = controller.handle_failure(
        request="Develop reusable document transform",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
    )

    assert "testing" in calls
    assert "review" in calls

    assert result.accepted is False
    assert result.evidence["promotion_decision"] == "rejected"
    assert controller.store.get("document.transform") is None


def test_verified_candidate_with_original_executor_reports_verified_retry():
    controller, _ = _controller()
    executions = []

    def execute_original(candidate, request):
        executions.append((candidate, request))
        return True

    result = controller.handle_failure(
        request="Convert report A to a structured summary",
        failure={"error": "unsupported operation"},
        classification=FailureClassification.MISSING_REUSABLE_CAPABILITY,
        capability_class="document.transform",
        execute_original=execute_original,
    )

    assert result.accepted is True
    assert result.retry_original_request is True
    assert result.evidence["retry_result"] is True
    assert len(executions) == 1
    assert executions[0][1] == (
        "Convert report A to a structured summary"
    )



def test_verified_candidate_requires_injected_promoter_before_store():
    """
    Independent verification and promotion are distinct controller stages.

    A verified worker proposal must cross a host-owned promoter before it
    becomes reusable.  The promoter may replace the untrusted worker proposal
    with the exact trusted artifact that actually crossed its boundary.
    """
    from sophyane.failure_driven_capability import (
        CapabilityDevelopmentController,
        FailureClassification,
        InMemoryCapabilityStore,
    )

    store = InMemoryCapabilityStore()
    calls = []

    worker_candidate = {
        "status": "SUCCESS",
        "provider": "codex_cli",
        "files": {
            "capability.py": "WORKER_PROPOSAL\n",
        },

        # Worker claims must not themselves grant promotion.
        "approved": True,
        "promoted": True,
    }

    trusted_candidate = {
        "status": "TRUSTED_PROMOTED",
        "provider": "codex_cli",
        "files": {
            "capability.py": "EXACT_TRUSTED_BYTES\n",
        },
    }

    def worker(role, _context):
        if role == "implementation":
            return worker_candidate
        return {
            "role": role,
            "proposal": "host-stage",
        }

    def verifier(candidate, request):
        calls.append(
            (
                "verify",
                candidate,
                request,
            )
        )
        return candidate is worker_candidate

    def promoter(candidate, request, capability_class):
        calls.append(
            (
                "promote",
                candidate,
                request,
                capability_class,
            )
        )

        assert candidate is worker_candidate
        assert capability_class == "test.capability"

        # This represents the host-owned trusted artifact produced by the
        # promotion boundary.  Only this value may enter the reusable store.
        return trusted_candidate

    controller = CapabilityDevelopmentController(
        store=store,
        worker=worker,
        verifier=verifier,
        promoter=promoter,
        max_attempts=1,
    )

    result = controller.handle_failure(
        request="Create the missing reusable capability.",
        failure="missing reusable implementation",
        classification=(
            FailureClassification.MISSING_REUSABLE_CAPABILITY
        ),
        capability_class="test.capability",
        execute_original=None,
    )

    assert result.accepted is True
    assert result.evidence["promotion_decision"] == "accepted"

    assert [item[0] for item in calls] == [
        "verify",
        "promote",
    ], (
        "verified candidate did not cross the distinct host-owned "
        "promotion stage"
    )

    assert (
        store.get("test.capability")
        is trusted_candidate
    ), (
        "reusable store did not receive the trusted promoter artifact"
    )

    assert (
        store.get("test.capability")
        is not worker_candidate
    ), (
        "untrusted worker proposal bypassed the promoter into the store"
    )

    # Promotion alone must not fabricate successful original-request retry.
    assert result.retry_original_request is False
    assert result.evidence["retry_result"] is None
