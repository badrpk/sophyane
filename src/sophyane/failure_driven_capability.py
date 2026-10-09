"""Failure-driven, bounded development of reusable execution capabilities.

This module is deliberately a controller, not a second execution runtime.  It
uses Sophyane's StateGraph for orchestration; workers only return proposals and
evidence.  The controller performs independent verification and is the only
place that promotes a candidate into the reusable capability store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from sophyane.graph_runtime import MemoryStore, StateGraph


class FailureClassification(str, Enum):
    MISSING_REUSABLE_CAPABILITY = "missing_reusable_capability"
    TRANSIENT_PROVIDER_FAILURE = "transient_provider_failure"
    SECURITY_AUTHORITY_RESTRICTION = "security_authority_restriction"
    INFEASIBLE_ENVIRONMENTAL_RESTRICTION = "infeasible_environmental_restriction"


class CapabilityStore(Protocol):
    def get(self, capability_class: str) -> Any | None: ...
    def put(self, capability_class: str, candidate: Any) -> None: ...


class InMemoryCapabilityStore:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def get(self, capability_class: str) -> Any | None:
        return self._items.get(str(capability_class))

    def put(self, capability_class: str, candidate: Any) -> None:
        self._items[str(capability_class)] = candidate


@dataclass
class CapabilityDevelopmentResult:
    accepted: bool
    retry_original_request: bool
    trace: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityReuseResult:
    reused: bool
    original_outcome_verified: bool
    evidence: dict[str, Any] = field(default_factory=dict)


Worker = Callable[[str, dict[str, Any]], Any]
Verifier = Callable[[Any, str], bool]
Promoter = Callable[[Any, str, str], Any]
Executor = Callable[[Any, str], bool]


class CapabilityDevelopmentController:
    """Run a bounded capability graph and own the promotion decision."""

    def __init__(
        self,
        *,
        store: CapabilityStore | None = None,
        worker: Worker | None = None,
        verifier: Verifier | None = None,
        promoter: Promoter | None = None,
        max_attempts: int = 3,
        _calls: list[str] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.store = store or InMemoryCapabilityStore()
        self.worker = worker or self._default_worker
        self.verifier = verifier or (lambda _candidate, _request: False)
        self.promoter = promoter
        self.max_attempts = int(max_attempts)
        self._calls = _calls

    @staticmethod
    def _default_worker(role: str, _context: dict[str, Any]) -> Any:
        # No default worker may silently manufacture a promotable capability.
        return {"role": role, "proposal": "unimplemented"}

    def _run_worker(self, role: str, context: dict[str, Any]) -> Any:
        if self._calls is not None:
            self._calls.append(role)
        return self.worker(role, context)

    def handle_failure(
        self,
        *,
        request: str,
        failure: Any,
        classification: FailureClassification,
        capability_class: str,
        execute_original: Executor | None = None,
    ) -> CapabilityDevelopmentResult:
        context = {
            "request": request,
            "failure": failure,
            "classification": classification.value,
            "capability_class": capability_class,
            "attempt": 0,
        }
        state: dict[str, Any] = {
            **context,
            "trace": [],
            "worker_evidence": [],
            "attempts": 0,
            "unresolved_failures": [],
            "candidate": None,
            "candidate_verified": False,
            "accepted": False,
            "retry_original_request": False,
            "promotion_decision": "rejected",
        }
        graph = self._build_graph(execute_original)
        result = graph.invoke(
            state,
            recursion_limit=4 + self.max_attempts * 6,
            return_result=True,
        )
        final = result.state
        evidence = {
            "original_unresolved_failure": failure,
            "classification": final.get(
                "classification",
                classification.value,
            ),
            "environmental_restriction": bool(
                final.get("environmental_restriction", False)
            ),
            "sandbox_unavailable": bool(
                final.get("sandbox_unavailable", False)
            ),
            "capability_gap": capability_class,
            "attempts": final.get("attempts", 0),
            "worker_participation": final.get("worker_evidence", []),
            "hypotheses": final.get("hypotheses", []),
            "test_results": final.get("test_results", []),
            "review_findings": final.get("review_findings", []),
            "diff_change_summary": final.get("diff_change_summary", {}),
            "graph_transitions": list(result.trace),
            "unresolved_failures": final.get("unresolved_failures", []),
            "verification_evidence": final.get("verification_evidence", []),
            "promotion_decision": final.get("promotion_decision", "rejected"),
            "retry_result": final.get("retry_result"),
            "decision": final.get("decision", "capability_development"),
        }
        return CapabilityDevelopmentResult(
            accepted=bool(final.get("accepted")),
            retry_original_request=bool(final.get("retry_original_request")),
            trace=list(result.trace),
            evidence=evidence,
        )

    def execute_or_reuse(
        self,
        *,
        request: str,
        capability_class: str,
        execute: Executor,
    ) -> CapabilityReuseResult:
        candidate = self.store.get(capability_class)
        if candidate is None:
            return CapabilityReuseResult(
                reused=False,
                original_outcome_verified=False,
                evidence={"capability_class": capability_class, "decision": "not_reusable"},
            )
        verified = bool(execute(candidate, request))
        return CapabilityReuseResult(
            reused=True,
            original_outcome_verified=verified,
            evidence={
                "capability_class": capability_class,
                "decision": "reused_verified_capability" if verified else "reused_but_original_failed",
            },
        )

    def _build_graph(self, execute_original: Executor | None) -> StateGraph:
        graph = StateGraph(MemoryStore())

        def add_trace(name: str, state: dict[str, Any]) -> dict[str, Any]:
            return {"trace": [name]}

        def analyze(state: dict[str, Any]) -> dict[str, Any]:
            if state["classification"] != FailureClassification.MISSING_REUSABLE_CAPABILITY.value:
                return {**add_trace("analyze_failure", state), "decision": "ordinary_failure"}
            return add_trace("analyze_failure", state)

        def discover(state: dict[str, Any]) -> dict[str, Any]:
            evidence = self._run_worker("failure_discovery", state)
            return {**add_trace("discover_capability_gap", state), "worker_evidence": [evidence]}

        def design(state: dict[str, Any]) -> dict[str, Any]:
            evidence = self._run_worker("design", state)
            return {
                **add_trace("design_candidate", state),
                "worker_evidence": [evidence],
                "hypotheses": [evidence],
            }

        def implement(state: dict[str, Any]) -> dict[str, Any]:
            attempt = int(state["attempts"]) + 1
            candidate = self._run_worker("implementation", {**state, "attempt": attempt})
            return {
                **add_trace("implement_candidate", state),
                "attempts": attempt,
                "candidate": candidate,
                "candidate_verified": False,
                "worker_evidence": [candidate],
                "diff_change_summary": (
                    candidate.get("diff_change_summary", {})
                    if isinstance(candidate, dict)
                    else getattr(candidate, "diff_change_summary", {})
                ),
            }

        def test(state: dict[str, Any]) -> dict[str, Any]:
            evidence = self._run_worker("testing", state)
            return {
                **add_trace("test_candidate", state),
                "worker_evidence": [evidence],
                "test_results": [evidence],
            }

        def review(state: dict[str, Any]) -> dict[str, Any]:
            evidence = self._run_worker("review", state)
            return {
                **add_trace("review_candidate", state),
                "worker_evidence": [evidence],
                "review_findings": [evidence],
            }

        def verify(state: dict[str, Any]) -> dict[str, Any]:
            try:
                passed = bool(
                    self.verifier(
                        state["candidate"],
                        state["request"],
                    )
                )
            except Exception as exc:
                # Sandbox absence is an environmental impossibility, not a
                # candidate defect.  It must terminate development without
                # retrying, promoting, or executing unverified candidate code.
                from sophyane.rsi.sandbox import SandboxUnavailable

                if not isinstance(exc, SandboxUnavailable):
                    raise

                return {
                    **add_trace("verify_candidate", state),
                    "classification": (
                        FailureClassification
                        .INFEASIBLE_ENVIRONMENTAL_RESTRICTION
                        .value
                    ),
                    "candidate_verified": False,
                    "accepted": False,
                    "retry_original_request": False,
                    "promotion_decision": "rejected",
                    "decision": "ordinary_failure",
                    "environmental_restriction": True,
                    "sandbox_unavailable": True,
                    "verification_evidence": [{
                        "attempt": state["attempts"],
                        "passed": False,
                        "sandbox_unavailable": True,
                        "error": str(exc),
                    }],
                    "unresolved_failures": [{
                        "attempt": state["attempts"],
                        "reason": "sandbox unavailable",
                    }],
                }

            unresolved = [] if passed else [
                {
                    "attempt": state["attempts"],
                    "reason": "independent verification failed",
                }
            ]
            return {
                **add_trace("verify_candidate", state),
                "candidate_verified": passed,
                "verification_evidence": [{
                    "attempt": state["attempts"],
                    "passed": passed,
                }],
                "unresolved_failures": unresolved,
            }

        def promote(state: dict[str, Any]) -> dict[str, Any]:
            if state["classification"] != FailureClassification.MISSING_REUSABLE_CAPABILITY.value:
                decision = (
                    "safe_terminal_restriction"
                    if state["classification"] == FailureClassification.SECURITY_AUTHORITY_RESTRICTION.value
                    else "ordinary_failure"
                )
                return {**add_trace("promote_or_reject", state), "decision": decision}
            if state.get("candidate_verified"):
                # The worker graph cannot grant promotion authority.  Reuse
                # Sophyane's canonical RSI authority boundary even for
                # non-source capability records.
                from sophyane.rsi.authority import Operation, require

                require("codex_cli", Operation.PROMOTION_OPERATION)

                trusted_candidate = state["candidate"]

                if self.promoter is not None:
                    trusted_candidate = self.promoter(
                        state["candidate"],
                        state["request"],
                        state["capability_class"],
                    )

                    if trusted_candidate is None:
                        return {
                            **add_trace("promote_or_reject", state),
                            "promotion_decision": "rejected",
                        }

                self.store.put(
                    state["capability_class"],
                    trusted_candidate,
                )

                return {
                    **add_trace("promote_or_reject", state),
                    "candidate": trusted_candidate,
                    "accepted": True,
                    "retry_original_request": True,
                    "promotion_decision": "accepted",
                    "promotion_authority": "sophyane.rsi.authority",
                }
            return {**add_trace("promote_or_reject", state), "promotion_decision": "rejected"}

        def retry(state: dict[str, Any]) -> dict[str, Any]:
            retry_result = None if execute_original is None else bool(
                execute_original(state["candidate"], state["request"])
            )
            return {**add_trace("retry_original_request", state), "retry_result": retry_result}

        def verify_original(state: dict[str, Any]) -> dict[str, Any]:
            # Candidate promotion and original-request verification are
            # distinct facts.  Without an executor there was no retry, and a
            # failed retry must likewise never become user-visible success.
            verified = state.get("retry_result") is True
            return {
                **add_trace("verify_original_outcome", state),
                "retry_original_request": verified,
            }

        graph.add_node("analyze_failure", analyze)
        graph.add_node("discover_capability_gap", discover)
        graph.add_node("design_candidate", design)
        graph.add_node("implement_candidate", implement)
        graph.add_node("test_candidate", test)
        graph.add_node("review_candidate", review)
        graph.add_node("verify_candidate", verify)
        graph.add_node("promote_or_reject", promote)
        graph.add_node("retry_original_request", retry)
        graph.add_node("verify_original_outcome", verify_original)
        graph.add_edge(StateGraph.START, "analyze_failure")
        graph.add_conditional_edges(
            "analyze_failure",
            lambda state: "develop" if state["classification"] == FailureClassification.MISSING_REUSABLE_CAPABILITY.value else "terminal",
            {"develop": "discover_capability_gap", "terminal": "promote_or_reject"},
        )
        graph.add_edge("discover_capability_gap", "design_candidate")
        graph.add_edge("design_candidate", "implement_candidate")
        graph.add_edge("implement_candidate", "test_candidate")
        graph.add_edge("test_candidate", "review_candidate")
        graph.add_edge("review_candidate", "verify_candidate")
        graph.add_conditional_edges(
            "verify_candidate",
            lambda state: (
                "environmental_restriction"
                if state.get("sandbox_unavailable")
                else (
                    "promote"
                    if state.get("candidate_verified")
                    else (
                        "retry_candidate"
                        if int(state["attempts"]) < self.max_attempts
                        else "reject"
                    )
                )
            ),
            {
                "promote": "promote_or_reject",
                "retry_candidate": "design_candidate",
                "reject": "promote_or_reject",
                "environmental_restriction": StateGraph.END,
            },
        )
        graph.add_conditional_edges(
            "promote_or_reject",
            lambda state: "retry" if state.get("accepted") else "end",
            {"retry": "retry_original_request", "end": StateGraph.END},
        )
        graph.add_edge("retry_original_request", "verify_original_outcome")
        graph.add_edge("verify_original_outcome", StateGraph.END)
        return graph


__all__ = [
    "CapabilityDevelopmentController",
    "CapabilityDevelopmentResult",
    "CapabilityReuseResult",
    "FailureClassification",
    "InMemoryCapabilityStore",
]
