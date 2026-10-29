"""Bounded orchestration for opt-in, auditable research runs."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import re
from threading import Event
from time import monotonic
from typing import Callable, Sequence

from sophyane.research.evaluation import TransferEvaluationReport


class ProblemState(str, Enum):
    known = "known"
    open = "open"
    underspecified = "underspecified"
    unknown = "unknown"


class ResearchStatus(str, Enum):
    established = "established"
    partial = "partial"
    unverified = "unverified"
    unresolved = "unresolved"
    insufficient_capability = "insufficient_capability"


@dataclass(frozen=True, slots=True)
class ResearchArtifact:
    role_id: str
    provider_id: str
    content: str
    route_id: str = ""
    resolved_model: str = "unknown"
    reviewed_role_ids: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    phase: str = "submission"
    captured_at: str = ""
    elapsed_seconds: float = 0.0
    prompt_version: str = "research-v1"
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchInput:
    question: str
    evidence: tuple[ResearchArtifact, ...] = ()
    prior_artifacts: tuple[ResearchArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchRole:
    role_id: str
    kind: str
    provider_id: str
    run: Callable[[ResearchInput], ResearchArtifact]
    external: bool = False
    available: bool = True
    unavailable_reason: str = "provider unavailable"
    prompt_version: str = "research-v1"
    cancel: Callable[[], None] | None = None
    route_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"evidence", "solver"}:
            raise ValueError("research role kind must be evidence or solver")
        if not self.role_id.strip() or not self.provider_id.strip():
            raise ValueError("research roles require stable role and provider identities")


@dataclass(frozen=True, slots=True)
class VerificationReport:
    supported_claims: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    as_of: str | None = None
    formal_check_state: str = "not_run"
    deterministic_checks: tuple[str, ...] = ()
    deterministic_checks_passed: bool = False
    citations_verified: bool = False
    authoritative_sources: bool = False
    target_resolved: bool = False
    problem_state_verified: bool = False
    new_theorem: bool = False
    independent_expert_review: bool = False
    problem_state: ProblemState = ProblemState.unknown


@dataclass(frozen=True, slots=True)
class MathematicalProgressReport:
    """Verifier-derived mathematical outcome, separate from transfer scores."""

    status: str = ResearchStatus.unverified.value
    verifier_supported_claims: tuple[str, ...] = ()
    verifier_unsupported_claims: tuple[str, ...] = ()
    formal_check_state: str = "not_run"
    deterministic_checks: tuple[str, ...] = ()
    deterministic_checks_passed: bool = False
    new_theorem_claimed: bool = False
    independent_expert_review: bool = False
    target_resolved: bool = False


@dataclass(frozen=True, slots=True)
class SkippedRole:
    role_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RoleFailure:
    role_id: str
    phase: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchPortfolioResult:
    question: str
    status: ResearchStatus
    problem_state: ProblemState
    artifacts: tuple[ResearchArtifact, ...]
    verification: VerificationReport
    citations: tuple[str, ...]
    disagreements: tuple[str, ...]
    skipped_roles: tuple[SkippedRole, ...] = ()
    failures: tuple[RoleFailure, ...] = ()
    as_of: str = ""
    cancelled: bool = False
    learning_error: str | None = None
    learning_summary: str = ""
    synthesis: str = ""
    mathematical_progress: MathematicalProgressReport = field(default_factory=MathematicalProgressReport)
    self_improvement: TransferEvaluationReport = field(default_factory=TransferEvaluationReport)


class ResearchPortfolioCoordinator:
    """Run evidence collection, independent submissions, then cross-review."""

    def run(
        self,
        question: str,
        *,
        evidence_roles: Sequence[ResearchRole] = (),
        solver_roles: Sequence[ResearchRole],
        allow_external: bool = False,
        timeout_seconds: float = 180.0,
        max_workers: int = 4,
        max_role_calls: int = 12,
        evidence_max_calls: int | None = None,
        solver_max_calls: int | None = None,
        verifier_max_calls: int | None = None,
        verifier: Callable[[tuple[ResearchArtifact, ...]], VerificationReport] | None = None,
        self_improvement_report: TransferEvaluationReport | None = None,
        learning_sink: Callable[[ResearchPortfolioResult], None] | None = None,
        cancel_event: Event | None = None,
        pre_skipped_roles: Sequence[SkippedRole] = (),
    ) -> ResearchPortfolioResult:
        if not question.strip():
            raise ValueError("research question must not be empty")
        explicit_budgets = (evidence_max_calls, solver_max_calls, verifier_max_calls)
        if any(value is not None and value < 0 for value in explicit_budgets):
            raise ValueError("role budgets must be non-negative")
        if timeout_seconds <= 0 or max_workers < 1 or max_role_calls < 1:
            raise ValueError("timeout_seconds, max_workers, and max_role_calls must be positive")

        started = monotonic()
        deadline = started + timeout_seconds
        artifacts: list[ResearchArtifact] = []
        skipped: list[SkippedRole] = list(pre_skipped_roles)
        failures: list[RoleFailure] = []
        cancelled = False

        separate_budgets = any(value is not None for value in explicit_budgets)
        remaining_calls = max_role_calls
        eligible_evidence, evidence_policy_skips = self._eligible_roles(
            tuple(evidence_roles), allow_external, expected_kind="evidence"
        )
        skipped.extend(evidence_policy_skips)
        evidence_limit = evidence_max_calls if evidence_max_calls is not None else max_role_calls
        selected_evidence = eligible_evidence[:evidence_limit]
        skipped.extend(
            SkippedRole(role.role_id, "role-call budget exhausted")
            for role in eligible_evidence[evidence_limit:]
        )
        if not separate_budgets:
            remaining_calls -= len(selected_evidence)
        eligible_solvers, solver_skips = self._eligible_roles(
            tuple(solver_roles), allow_external, expected_kind="solver"
        )
        skipped.extend(solver_skips)
        solver_limit = solver_max_calls if solver_max_calls is not None else (
            max_role_calls if separate_budgets else remaining_calls
        )
        selected_solvers = eligible_solvers[:solver_limit]
        skipped.extend(
            SkippedRole(role.role_id, "role-call budget exhausted")
            for role in eligible_solvers[solver_limit:]
        )
        if not separate_budgets:
            remaining_calls -= len(selected_solvers)
        # Evidence gathering and independent solver submissions share the
        # same deadline. Solvers start without retrieved evidence; review gets
        # the frozen evidence after both phases finish.
        if selected_evidence and selected_solvers and max_workers > 1:
            evidence_workers = max(1, max_workers // 2)
            solver_workers = max(1, max_workers - evidence_workers)
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sophyane-research-stage") as stages:
                evidence_future = stages.submit(
                    self._capture_roles, selected_evidence, ResearchInput(question), deadline,
                    evidence_workers, allow_external, cancel_event, "evidence",
                    expected_kind="evidence",
                )
                solver_future = stages.submit(
                    self._capture_roles, selected_solvers, ResearchInput(question), deadline,
                    solver_workers, allow_external, cancel_event, "submission",
                    expected_kind="solver",
                )
                evidence, evidence_skips, evidence_failures, evidence_cancelled = evidence_future.result()
                initial, initial_skips, initial_failures, solver_cancelled = solver_future.result()
        else:
            if selected_evidence and selected_solvers:
                initial, initial_skips, initial_failures, solver_cancelled = self._capture_roles(
                    selected_solvers, ResearchInput(question), deadline, max_workers,
                    allow_external, cancel_event, "submission", expected_kind="solver",
                )
                evidence, evidence_skips, evidence_failures, evidence_cancelled = self._capture_roles(
                    selected_evidence, ResearchInput(question), deadline, max_workers,
                    allow_external, cancel_event, "evidence", expected_kind="evidence",
                )
            else:
                evidence, evidence_skips, evidence_failures, evidence_cancelled = self._capture_roles(
                    selected_evidence, ResearchInput(question), deadline, max_workers,
                    allow_external, cancel_event, "evidence", expected_kind="evidence",
                )
                initial, initial_skips, initial_failures, solver_cancelled = self._capture_roles(
                    selected_solvers, ResearchInput(question), deadline, max_workers,
                    allow_external, cancel_event, "submission", expected_kind="solver",
                )
        artifacts.extend(evidence)
        artifacts.extend(initial)
        skipped.extend(evidence_skips)
        skipped.extend(initial_skips)
        failures.extend(evidence_failures)
        failures.extend(initial_failures)
        cancelled |= evidence_cancelled or solver_cancelled

        # Reviewer prompts are built only after all initial solver futures have
        # completed or reached the shared deadline.
        if not cancelled and monotonic() < deadline and not (cancel_event and cancel_event.is_set()):
            # Build each review input from the frozen initial submissions,
            # and run those reviews together after every submission landed.
            reviewers = tuple(role for role in eligible_solvers if any(
                item.role_id != role.role_id for item in initial
            ))
            verifier_limit = verifier_max_calls if verifier_max_calls is not None else (
                max_role_calls if separate_budgets else remaining_calls
            )
            selected_reviewers = reviewers[:verifier_limit]
            skipped.extend(
                SkippedRole(role.role_id, "role-call budget exhausted")
                for role in reviewers[verifier_limit:]
            )
            reviewed, review_skips, review_failures, was_cancelled = self._capture_roles(
                selected_reviewers,
                lambda role: ResearchInput(
                    question,
                    evidence=tuple(evidence),
                    prior_artifacts=tuple(item for item in initial if item.role_id != role.role_id),
                ),
                deadline,
                max_workers,
                allow_external,
                cancel_event,
                "review",
                expected_kind="solver",
            )
            artifacts.extend(reviewed)
            skipped.extend(review_skips)
            failures.extend(review_failures)
            cancelled |= was_cancelled

        ordered = tuple(sorted(artifacts, key=lambda item: (item.role_id, item.phase, item.provider_id)))
        verifier_enabled = verifier is not None and (
            verifier_max_calls is None or verifier_max_calls > 0
        )
        report = self._verify(
            verifier if verifier_enabled else None,
            ordered, max(0.0, deadline - monotonic()), cancel_event
        )
        cancelled = cancelled or bool(cancel_event and cancel_event.is_set())
        status = self._status(report, initial)
        as_of = report.as_of or datetime.now(timezone.utc).date().isoformat()
        result = ResearchPortfolioResult(
            question=question,
            status=status,
            problem_state=(
                report.problem_state
                if report.problem_state_verified
                and report.citations
                and report.citations_verified
                and report.authoritative_sources
                and report.as_of
                and (report.problem_state is not ProblemState.known or report.target_resolved)
                else ProblemState.unknown
            ),
            artifacts=ordered,
            verification=report,
            citations=tuple(sorted(set(report.citations).union(*(set(a.citations) for a in ordered)))),
            disagreements=report.unsupported_claims,
            skipped_roles=tuple(sorted(skipped, key=lambda item: (item.role_id, item.reason))),
            failures=tuple(sorted(failures, key=lambda item: (item.role_id, item.phase, item.reason))),
            as_of=as_of,
            cancelled=cancelled or bool(cancel_event and cancel_event.is_set()),
            mathematical_progress=MathematicalProgressReport(
                status=_mathematical_progress_status(report),
                verifier_supported_claims=report.supported_claims,
                verifier_unsupported_claims=report.unsupported_claims,
                formal_check_state=report.formal_check_state,
                deterministic_checks=report.deterministic_checks,
                deterministic_checks_passed=report.deterministic_checks_passed,
                new_theorem_claimed=report.new_theorem,
                independent_expert_review=report.independent_expert_review,
                target_resolved=report.target_resolved,
            ),
            self_improvement=self_improvement_report or TransferEvaluationReport(),
        )
        result = replace(result, synthesis=self._synthesis(status, report, as_of, ordered))
        if (
            learning_sink is not None
            and status in {ResearchStatus.established, ResearchStatus.partial}
            and not cancelled
            and not (cancel_event and cancel_event.is_set())
        ):
            checked_summary = "\n".join(
                (
                    f"Status: {status.value}",
                    "Checked claims:",
                    *(f"- {claim}" for claim in report.supported_claims),
                    *(f"- Limitation: {claim}" for claim in report.unsupported_claims),
                    f"As of: {as_of}",
                )
            )
            learning_view = replace(
                result,
                artifacts=(),
                failures=(),
                skipped_roles=(),
                learning_summary=checked_summary,
            )
            remaining = deadline - monotonic()
            if remaining <= 0:
                result = replace(result, learning_error="learning sink skipped after portfolio deadline")
            else:
                pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sophyane-research-learning")
                future = pool.submit(learning_sink, learning_view)
                try:
                    learning_deadline = monotonic() + remaining
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            future.cancel()
                            result = replace(result, learning_error="learning sink cancelled")
                            break
                        remaining = learning_deadline - monotonic()
                        if remaining <= 0:
                            future.cancel()
                            result = replace(result, learning_error="learning sink deadline exceeded")
                            break
                        try:
                            future.result(timeout=min(remaining, 0.05))
                            break
                        except TimeoutError as exc:
                            if future.done():
                                result = replace(result, learning_error=_safe_error(exc))
                                break
                except TimeoutError:
                    result = replace(result, learning_error="learning sink deadline exceeded")
                except Exception as exc:  # learning must not alter research outcome
                    result = replace(result, learning_error=_safe_error(exc))
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
        return replace(
            result,
            cancelled=result.cancelled or bool(cancel_event and cancel_event.is_set()),
        )

    @staticmethod
    def _eligible_roles(
        roles: tuple[ResearchRole, ...], allow_external: bool, *, expected_kind: str | None = None
    ) -> tuple[tuple[ResearchRole, ...], tuple[SkippedRole, ...]]:
        eligible: list[ResearchRole] = []
        skipped: list[SkippedRole] = []
        providers: set[str] = set()
        role_ids: set[str] = set()
        cascade_leaves = {
            route.split(":", 1)[0]
            for role in roles
            if role.provider_id.startswith("mode6-cascade:") or role.role_id.startswith("mode6-")
            for route in role.route_keys
        }
        for role in sorted(roles, key=lambda item: (item.role_id, item.provider_id)):
            if role.role_id in role_ids:
                skipped.append(SkippedRole(role.role_id, "duplicate role id"))
            elif expected_kind is not None and role.kind != expected_kind:
                skipped.append(SkippedRole(role.role_id, f"role kind is not {expected_kind}"))
            elif role.external and not allow_external:
                skipped.append(SkippedRole(role.role_id, "external research not allowed"))
            elif not role.available:
                skipped.append(SkippedRole(role.role_id, role.unavailable_reason))
            elif _provider_route_keys(role, cascade_leaves).intersection(providers):
                skipped.append(SkippedRole(role.role_id, "duplicate provider route"))
            else:
                eligible.append(role)
                providers.update(_provider_route_keys(role, cascade_leaves))
            role_ids.add(role.role_id)
        return tuple(eligible), tuple(skipped)

    @classmethod
    def _capture_roles(
        cls,
        roles: tuple[ResearchRole, ...],
        request: ResearchInput | Callable[[ResearchRole], ResearchInput],
        deadline: float,
        max_workers: int,
        allow_external: bool,
        cancel_event: Event | None,
        phase: str,
        *,
        expected_kind: str | None = None,
    ) -> tuple[list[ResearchArtifact], list[SkippedRole], list[RoleFailure], bool]:
        eligible, skipped = cls._eligible_roles(roles, allow_external, expected_kind=expected_kind)
        skipped = list(skipped)
        if not eligible:
            return [], list(skipped), [], bool(cancel_event and cancel_event.is_set())
        if cancel_event and cancel_event.is_set():
            return [], list(skipped) + [SkippedRole(r.role_id, "cancelled") for r in eligible], [], True
        if monotonic() >= deadline:
            return [], list(skipped), [RoleFailure(r.role_id, phase, "deadline exceeded") for r in eligible], False

        pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sophyane-research")
        futures: dict[Future[ResearchArtifact], ResearchRole] = {
            pool.submit(
                cls._invoke_role,
                role,
                request(role) if callable(request) else request,
                phase,
            ): role
            for role in eligible
        }
        done: set[Future[ResearchArtifact]] = set()
        pending = set(futures)
        while pending and monotonic() < deadline and not (cancel_event and cancel_event.is_set()):
            finished, pending = wait(
                pending,
                timeout=min(0.05, max(0.0, deadline - monotonic())),
                return_when=FIRST_COMPLETED,
            )
            done.update(finished)
        was_cancelled = bool(cancel_event and cancel_event.is_set())
        completed_pending = {
            future for future in pending if future.done() and not future.cancelled()
        }
        done.update(completed_pending)
        pending.difference_update(completed_pending)
        for future in tuple(pending):
            future.cancel()
            cancel = futures[future].cancel
            if cancel is not None:
                try:
                    cancel()
                except Exception:
                    pass
        completed_pending = {
            future for future in pending if future.done() and not future.cancelled()
        }
        done.update(completed_pending)
        pending.difference_update(completed_pending)
        pool.shutdown(wait=False, cancel_futures=True)

        artifacts: list[ResearchArtifact] = []
        failures: list[RoleFailure] = []
        for future in done:
            role = futures[future]
            try:
                artifact = future.result()
                artifacts.append(artifact)
            except Exception as exc:
                failures.append(RoleFailure(role.role_id, phase, _safe_error(exc)))
        if pending and was_cancelled:
            skipped = list(skipped) + [SkippedRole(futures[f].role_id, "cancelled") for f in pending]
        elif pending:
            failures.extend(RoleFailure(futures[f].role_id, phase, "deadline exceeded") for f in pending)
        artifacts.sort(key=lambda item: (item.role_id, item.provider_id))
        failures.sort(key=lambda item: (item.role_id, item.phase, item.reason))
        skipped.sort(key=lambda item: (item.role_id, item.reason))
        return artifacts, list(skipped), failures, was_cancelled

    @staticmethod
    def _invoke_role(role: ResearchRole, request: ResearchInput, phase: str) -> ResearchArtifact:
        started = monotonic()
        artifact = role.run(request)
        if not isinstance(artifact, ResearchArtifact):
            raise TypeError("role did not return a ResearchArtifact")
        return replace(
            artifact,
            role_id=role.role_id,
            provider_id=artifact.provider_id or role.provider_id,
            route_id=role.provider_id,
            phase=phase,
            captured_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=max(0.0, monotonic() - started),
            prompt_version=role.prompt_version,
            reviewed_role_ids=(
                tuple(item.role_id for item in request.prior_artifacts)
                if phase == "review" else ()
            ),
        )

    @staticmethod
    def _verify(
        verifier: Callable[[tuple[ResearchArtifact, ...]], VerificationReport] | None,
        artifacts: tuple[ResearchArtifact, ...],
        timeout_seconds: float,
        cancel_event: Event | None,
    ) -> VerificationReport:
        if verifier is None:
            return VerificationReport()
        if cancel_event is not None and cancel_event.is_set():
            return VerificationReport(unsupported_claims=("verification cancelled",))
        if timeout_seconds <= 0:
            return VerificationReport(unsupported_claims=("verification deadline exceeded",))
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sophyane-research-verifier")
        future = pool.submit(verifier, artifacts)
        deadline = monotonic() + timeout_seconds
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    future.cancel()
                    return VerificationReport(unsupported_claims=("verification cancelled",))
                remaining = deadline - monotonic()
                if remaining <= 0:
                    future.cancel()
                    return VerificationReport(unsupported_claims=("verification deadline exceeded",))
                try:
                    report = future.result(timeout=min(remaining, 0.05))
                    if cancel_event is not None and cancel_event.is_set():
                        return VerificationReport(unsupported_claims=("verification cancelled",))
                    break
                except TimeoutError as exc:
                    if future.done():
                        return VerificationReport(
                            unsupported_claims=(f"verification failed: {_safe_error(exc)}",)
                        )
                    continue
            if not isinstance(report, VerificationReport):
                raise TypeError("verifier did not return a VerificationReport")
            return report
        except Exception as exc:
            return VerificationReport(
                unsupported_claims=(f"verification failed: {_safe_error(exc)}",)
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _status(report: VerificationReport, solver_artifacts: Sequence[ResearchArtifact]) -> ResearchStatus:
        if not solver_artifacts:
            return ResearchStatus.insufficient_capability
        source_backed = bool(
            report.supported_claims
            and report.citations
            and report.citations_verified
            and report.authoritative_sources
        )
        deterministic_backed = bool(
            report.supported_claims
            and report.deterministic_checks
            and report.deterministic_checks_passed
        )
        checked_support = source_backed or deterministic_backed
        if report.new_theorem and not report.independent_expert_review:
            return ResearchStatus.unverified
        if checked_support and (report.unsupported_claims or not report.target_resolved):
            return ResearchStatus.partial
        current_open_status = bool(
            report.problem_state is ProblemState.open
            and report.problem_state_verified
            and report.citations
            and report.citations_verified
            and report.authoritative_sources
            and report.as_of
        )
        if current_open_status:
            return ResearchStatus.unresolved
        if report.target_resolved and checked_support and not report.unsupported_claims:
            return ResearchStatus.established
        return ResearchStatus.unverified

    @staticmethod
    def _synthesis(
        status: ResearchStatus,
        report: VerificationReport,
        as_of: str,
        artifacts: Sequence[ResearchArtifact],
    ) -> str:
        lines = [f"Research status: {status.value}"]
        if status is ResearchStatus.established:
            lines.append("Verified findings:")
            lines.extend(f"- {claim}" for claim in report.supported_claims)
        elif status is ResearchStatus.partial:
            lines.append("Verified partial findings:")
            lines.extend(f"- {claim}" for claim in report.supported_claims)
            lines.append("Unresolved or unsupported claims:")
            lines.extend(f"- {claim}" for claim in report.unsupported_claims)
            if not report.unsupported_claims and not report.target_resolved:
                lines.append("- The research target is not fully resolved.")
        elif status is ResearchStatus.unresolved:
            lines.append(f"No verified resolution is established as of {as_of}.")
        elif status is ResearchStatus.insufficient_capability:
            lines.append("Insufficient capability: no solver role completed successfully.")
        elif report.new_theorem and not report.independent_expert_review:
            lines.append("Novel theorem claim remains unverified; independent expert review is required.")
            lines.extend(f"- Verifier-reported supporting claim: {claim}" for claim in report.supported_claims)
            lines.extend(f"- Unresolved proof obligation: {claim}" for claim in report.unsupported_claims)
        else:
            lines.append("No claims passed the configured verification checks.")
            candidates = [item for item in artifacts if item.phase != "evidence"]
            if candidates:
                lines.append("Candidate analyses (unverified):")
                for artifact in candidates:
                    excerpt = artifact.content.strip()
                    if len(excerpt) > 1200:
                        excerpt = excerpt[:1197] + "..."
                    lines.append(f"- {artifact.role_id} ({artifact.phase}): {excerpt}")
        submitted = {item.role_id for item in artifacts if item.phase == "submission"}
        reviewed = {
            role_id for item in artifacts if item.phase == "review"
            for role_id in item.reviewed_role_ids
        }
        unreviewed = sorted(submitted - reviewed)
        if unreviewed:
            lines.append(
                "No independent cross-review was available for: " + ", ".join(unreviewed) + "."
            )
        return "\n".join(lines)


def _safe_error(error: BaseException) -> str:
    message = str(error)
    message = re.sub(
        r"(?i)\b(api[-_ ]?key|token|secret|password|authorization)\b\s*[:=]\s*('[^']*'|\"[^\"]*\"|[^\s,;]+)",
        r"\1=[REDACTED]",
        message,
    )
    message = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", message)
    message = re.sub(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", message)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _provider_route_keys(role: ResearchRole, cascade_leaves: set[str]) -> set[str]:
    """Normalize direct provider/model IDs and cascade leaf identities."""
    identities = {role.provider_id, *role.route_keys}
    normalized = set(identities)
    normalized.update(
        identity.split(":", 1)[0]
        for identity in identities
        if identity.split(":", 1)[0] in cascade_leaves
    )
    return normalized


def _mathematical_progress_status(report: VerificationReport) -> str:
    """Classify only verifier evidence; benchmark and role status are excluded."""
    source_checked = bool(
        report.supported_claims
        and report.citations
        and report.citations_verified
        and report.authoritative_sources
    )
    deterministic_checked = bool(
        report.supported_claims
        and report.deterministic_checks
        and report.deterministic_checks_passed
    )
    checked = source_checked or deterministic_checked
    if report.new_theorem and not report.independent_expert_review:
        return "unverified_new_theorem_claim"
    if report.problem_state is ProblemState.open and report.problem_state_verified and source_checked:
        return "open_problem"
    if report.target_resolved and checked and not report.unsupported_claims:
        return "target_resolved"
    if report.supported_claims and checked:
        return "partial"
    return "unverified"
