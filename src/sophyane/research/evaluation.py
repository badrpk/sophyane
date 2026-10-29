"""Research response rubrics and cautious matched-score transfer evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Mapping


@dataclass(frozen=True, slots=True)
class TransferEvaluationReport:
    """A cautious matched-score summary; never a causal or truth certificate."""

    status: str = "not_evaluated"
    task_count: int = 0
    domain_count: int = 0
    minimum_tasks: int = 5
    minimum_domains: int = 3
    mean_baseline: float | None = None
    mean_post: float | None = None
    mean_delta: float | None = None
    domain_deltas: dict[str, float] = field(default_factory=dict)
    regressed_tasks: tuple[str, ...] = ()
    task_ids: tuple[str, ...] = ()
    baseline_holdout_version: str = ""
    post_holdout_version: str = ""
    baseline_rubric_version: str = ""
    post_rubric_version: str = ""
    baseline_system_version: str = ""
    post_system_version: str = ""
    holdout_confirmed: bool = False
    causal_claim_supported: bool = False
    interpretation: str = "No paired held-out evaluation was supplied."

    def __post_init__(self) -> None:
        if self.causal_claim_supported:
            raise ValueError("transfer score comparisons cannot certify causal improvement")
        if self.status == "positive_transfer_signal":
            if not self.holdout_confirmed:
                raise ValueError("positive transfer signals require confirmed holdout isolation")
            if self.task_count < self.minimum_tasks or self.domain_count < self.minimum_domains:
                raise ValueError("positive transfer signals require minimum task and domain coverage")
            if self.mean_delta is None or self.mean_delta <= 0:
                raise ValueError("positive transfer signals require a positive mean score delta")
            if not self.domain_deltas or any(delta < 0 for delta in self.domain_deltas.values()):
                raise ValueError("positive transfer signals cannot include a regressing domain")
            if len(self.task_ids) != self.task_count or len(set(self.task_ids)) != self.task_count:
                raise ValueError("positive transfer signals require the complete unique task id list")
            if len(self.domain_deltas) != self.domain_count:
                raise ValueError("positive transfer signals require one delta for every domain")
            if not self.baseline_rubric_version or self.baseline_rubric_version != self.post_rubric_version:
                raise ValueError("positive transfer signals require a shared recorded rubric version")
            if not self.baseline_holdout_version or self.baseline_holdout_version != self.post_holdout_version:
                raise ValueError("positive transfer signals require the same recorded holdout version")
            if not self.baseline_system_version or not self.post_system_version:
                raise ValueError("positive transfer signals require baseline and post system versions")
            if self.baseline_system_version == self.post_system_version:
                raise ValueError("positive transfer signals require distinct system versions")


def compare_transfer_scores(
    baseline_scores: Mapping[str, float],
    post_scores: Mapping[str, float],
    task_domains: Mapping[str, str],
    *,
    minimum_tasks: int = 5,
    minimum_domains: int = 3,
    holdout_confirmed: bool = False,
    baseline_holdout_version: str = "",
    post_holdout_version: str = "",
    baseline_rubric_version: str = "",
    post_rubric_version: str = "",
    baseline_system_version: str = "",
    post_system_version: str = "",
) -> TransferEvaluationReport:
    """Compare fixed-holdout scores from before and after one research cycle.

    Scores must share identical task IDs and lie in [0, 1]. A positive result
    is only a transfer signal: this aggregate comparison cannot establish that
    a research change caused the gain or that it generalizes broadly.
    """
    if minimum_tasks < 1 or minimum_domains < 1:
        raise ValueError("minimum task and domain counts must be positive")
    baseline = dict(baseline_scores)
    post = dict(post_scores)
    domains = dict(task_domains)
    if not baseline and not post and not domains:
        return TransferEvaluationReport(
            minimum_tasks=minimum_tasks,
            minimum_domains=minimum_domains,
        )
    if set(baseline) != set(post):
        raise ValueError("baseline and post-cycle scores must use the same task ids")
    if set(baseline) != set(domains):
        raise ValueError("every scored task must have exactly one domain label")
    if baseline_rubric_version != post_rubric_version:
        raise ValueError("baseline and post-cycle scores must use the same rubric version")
    if baseline_holdout_version != post_holdout_version:
        raise ValueError("baseline and post-cycle scores must use the same holdout version")
    if holdout_confirmed and not baseline_rubric_version.strip():
        raise ValueError("confirmed holdout comparisons require a recorded rubric version")
    if holdout_confirmed and not baseline_holdout_version.strip():
        raise ValueError("confirmed holdout comparisons require a recorded holdout version")
    if any(not isinstance(task_id, str) or not task_id.strip() for task_id in baseline):
        raise ValueError("task ids must be non-empty strings")
    if any(not isinstance(domain, str) or not domain.strip() for domain in domains.values()):
        raise ValueError("domain labels must be non-empty strings")
    if any(
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not 0 <= score <= 1
        or not math.isfinite(score)
        for score in (*baseline.values(), *post.values())
    ):
        raise ValueError("scores must be finite values between 0 and 1")

    task_ids = sorted(baseline)
    deltas = {task_id: float(post[task_id]) - float(baseline[task_id]) for task_id in task_ids}
    grouped: dict[str, list[float]] = {}
    for task_id in task_ids:
        grouped.setdefault(domains[task_id].strip(), []).append(deltas[task_id])
    domain_deltas = {
        domain: round(math.fsum(values) / len(values), 12)
        for domain, values in sorted(grouped.items())
    }
    mean_baseline = math.fsum(float(baseline[item]) for item in task_ids) / len(task_ids)
    mean_post = math.fsum(float(post[item]) for item in task_ids) / len(task_ids)
    mean_delta = mean_post - mean_baseline
    enough_coverage = len(task_ids) >= minimum_tasks and len(grouped) >= minimum_domains
    if not enough_coverage:
        status = "insufficient_coverage"
        interpretation = "Matched scores exist, but the predeclared task/domain minimum was not met."
    elif not holdout_confirmed:
        status = "holdout_unconfirmed"
        interpretation = "Matched scores exist, but holdout isolation was not confirmed."
    elif mean_delta > 0 and all(delta >= 0 for delta in domain_deltas.values()):
        status = "positive_transfer_signal"
        interpretation = "Mean score improved without a domain-level mean regression; this is not causal proof."
    elif mean_delta < 0 and all(delta <= 0 for delta in domain_deltas.values()):
        status = "negative_transfer_signal"
        interpretation = "Mean score declined across domains."
    elif mean_delta == 0 and all(delta == 0 for delta in domain_deltas.values()):
        status = "no_gain"
        interpretation = "No score change was measured on the matched holdout."
    else:
        status = "mixed"
        interpretation = "Aggregate and domain-level outcomes are mixed; do not claim general improvement."

    return TransferEvaluationReport(
        status=status,
        task_count=len(task_ids),
        domain_count=len(grouped),
        minimum_tasks=minimum_tasks,
        minimum_domains=minimum_domains,
        mean_baseline=mean_baseline,
        mean_post=mean_post,
        mean_delta=mean_delta,
        domain_deltas=domain_deltas,
        regressed_tasks=tuple(task for task in task_ids if deltas[task] < 0),
        task_ids=tuple(task_ids),
        baseline_holdout_version=baseline_holdout_version,
        post_holdout_version=post_holdout_version,
        baseline_rubric_version=baseline_rubric_version,
        post_rubric_version=post_rubric_version,
        baseline_system_version=baseline_system_version,
        post_system_version=post_system_version,
        holdout_confirmed=holdout_confirmed,
        causal_claim_supported=False,
        interpretation=interpretation,
    )


_RUBRICS: dict[str, tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]] = {
    "ode_decay": (
        ("equation and initial value", (re.compile(r"(?=.*y'\s*=\s*-?2\s*y)(?=.*y\s*\(\s*0\s*\)\s*=\s*3)", re.I | re.S),)),
        ("closed-form solution", (re.compile(r"3\s*(?:\*|·)?\s*e\s*\^?\s*\{?\s*-\s*2\s*t?\s*\}?", re.I), re.compile(r"3\s*\*?\s*exp\s*\(\s*-\s*2\s*t\s*\)", re.I))),
        ("value at one", (re.compile(r"y\s*\(\s*1\s*\)\s*=\s*3\s*(?:\*|·)?\s*e\s*\^?\s*\{?\s*-\s*2\s*\}?", re.I), re.compile(r"0\.40[0-9]+"))),
        ("substitution check", (re.compile(r"y'\s*=\s*-\s*6\s*(?:\*|·)?\s*e\s*\^?\s*\{?\s*-\s*2\s*t\s*\}?", re.I), re.compile(r"differentiating.{0,50}-\s*6", re.I))),
    ),
    "ftcs_heat": (
        ("amplification factor", (re.compile(r"g\s*=\s*1\s*-\s*4\s*r.{0,50}sin\s*\^?\s*2", re.I), re.compile(r"1\s*-\s*4\s*r.{0,50}sin\s*\^?\s*2", re.I))),
        ("diffusion number", (re.compile(r"r\s*=\s*(?:ν|nu)\s*\*?\s*dt\s*/\s*dx\s*\^?\s*2", re.I), re.compile(r"diffusion number\s+r", re.I))),
        ("stability bound", (re.compile(r"(?:0\s*(?:<=|≤)\s*)?r\s*(?:<=|≤)\s*1\s*/\s*2", re.I),)),
    ),
    "navier_stokes_3d": (
        ("open status", (re.compile(r"\bopen\b", re.I), re.compile(r"unresolved", re.I))),
        ("energy inequality", (re.compile(r"(?=.*energy inequality)(?=.*2\s*(?:ν|nu).{0,100}integral.{0,100}(?:∇|nabla).{0,100}(?:≤|<=).{0,80}u\s*[_\{]?0)", re.I | re.S),)),
        ("Serrin integrability condition", (re.compile(r"(?=.*2\s*/\s*q\s*\+\s*3\s*/\s*p\s*=\s*1)(?=.*l\s*\^?\s*q.{0,30}l\s*\^?\s*p)", re.I | re.S),)),
        ("strict spatial exponent", (re.compile(r"p\s*>\s*3"),)),
    ),
}

_FORBIDDEN: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "ode_decay": (
        ("substitution is incorrect", re.compile(r"substitution\s+is\s+incorrect", re.I)),
        ("does not satisfy the initial condition", re.compile(r"does\s+not\s+satisfy\s+the\s+initial\s+condition", re.I)),
    ),
    "ftcs_heat": (
        ("imaginary eigenvalues imply instability", re.compile(r"(?:imaginary\s+eigenvalues|eigenvalues.{0,30}imaginary).{0,80}unstable", re.I)),
        ("unconditionally stable", re.compile(r"(?<!not )\bunconditionally\s+stable\b", re.I)),
    ),
    "navier_stokes_3d": (
        ("Lions lemma proves global regularity", re.compile(r"lions\s+lemma.{0,100}(?:prove|establish).{0,30}global\s+regularity", re.I)),
        ("global regularity is proved", re.compile(r"global\s+regularity\s+(?:has\s+been\s+)?proved", re.I)),
    ),
}


def score_science_response(problem_id: str, response: str) -> dict[str, object]:
    """Score presence of known critical elements and contradictions.

    This is a regression rubric for three fixed prompts. It does not parse
    proofs, validate citations, or certify that a response is mathematically
    true; a high score only means the expected textual checks were present.
    """
    problem_id = str(problem_id or "")
    response = str(response or "")
    rubric = _RUBRICS.get(problem_id)
    if rubric is None:
        return {
            "problem_id": problem_id,
            "score": 0,
            "max_score": 0,
            "passed": False,
            "missing": ["unknown problem id"],
            "contradictions": [],
            "evidence": {},
            "certifies_truth": False,
        }

    evidence: dict[str, list[str]] = {}
    missing: list[str] = []
    for label, alternatives in rubric:
        matches = [pattern.pattern for pattern in alternatives if pattern.search(response)]
        if matches:
            evidence[label] = matches
        else:
            missing.append(label)

    contradictions = [
        label for label, pattern in _FORBIDDEN.get(problem_id, ()) if pattern.search(response)
    ]
    score = len(evidence)
    return {
        "problem_id": problem_id,
        "score": score,
        "max_score": len(rubric),
        "passed": not missing and not contradictions,
        "missing": missing,
        "contradictions": contradictions,
        "evidence": evidence,
        "certifies_truth": False,
    }
