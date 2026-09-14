"""Small explicit bounded campaign engine around the existing RSI gates."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from .authority import AuthorityViolation, Operation, require, verify_mutation_authority

MAX_GENERATIONS = 20


class RedStatus(str, Enum):
    RED_CONFIRMED = "RED_CONFIRMED"
    RED_ALREADY_GREEN = "RED_ALREADY_GREEN"
    RED_UNRELATED = "RED_UNRELATED"
    RED_FLAKY_OR_NONDETERMINISTIC = "RED_FLAKY_OR_NONDETERMINISTIC"
    RED_UNAVAILABLE = "RED_UNAVAILABLE"


def classify_red(*, exit_code: int | None, expected_failure: str = "", output: str = "", runs: tuple[int, ...] = ()) -> RedStatus:
    """Classify host test evidence; provider output is never sufficient."""
    if exit_code is None:
        return RedStatus.RED_UNAVAILABLE
    if runs and len(set(runs)) > 1:
        return RedStatus.RED_FLAKY_OR_NONDETERMINISTIC
    if exit_code == 0:
        return RedStatus.RED_ALREADY_GREEN
    if exit_code != 1 or not expected_failure or expected_failure not in output:
        return RedStatus.RED_UNRELATED
    if "SyntaxError" in output or "ERROR collecting" in output or "ImportError" in output:
        return RedStatus.RED_UNRELATED
    return RedStatus.RED_CONFIRMED


@dataclass(frozen=True)
class BenchmarkManifest:
    regression_checks: tuple[tuple[str, ...], ...] = ()
    holdout_checks: tuple[tuple[str, ...], ...] = ()
    meta_improvement_checks: tuple[tuple[str, ...], ...] = ()
    scoring_weights: Mapping[str, float] = field(default_factory=lambda: {"capability": 0.7, "meta": 0.3})

    def canonical(self) -> str:
        payload = {"regression_checks": self.regression_checks, "holdout_checks": self.holdout_checks,
                   "meta_improvement_checks": self.meta_improvement_checks,
                   "scoring_weights": dict(sorted(self.scoring_weights.items()))}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


class BenchmarkChanged(RuntimeError):
    pass


class StopReason(str, Enum):
    PLATEAU = "PLATEAU"
    META_PLATEAU = "META_PLATEAU"
    CYCLING = "CYCLING"
    TEST_GAMING = "TEST_GAMING"
    CODE_BLOAT = "CODE_BLOAT"
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"
    REGRESSION = "REGRESSION"
    RSI_HANDOFF_BREAK = "RSI_HANDOFF_BREAK"
    NO_AUTONOMOUS_IMPROVEMENT = "NO_AUTONOMOUS_IMPROVEMENT"
    CONTEXT_DECAY = "CONTEXT_DECAY"
    TOOL_PROTOCOL_FAILURE = "TOOL_PROTOCOL_FAILURE"
    MAX_GENERATIONS = "MAX_GENERATIONS"


@dataclass(frozen=True)
class CandidateGate:
    authority_ok: bool = False
    weakness_grounded: bool = False
    red_status: RedStatus = RedStatus.RED_UNAVAILABLE
    focused_green: bool = False
    holdout_green: bool = False
    no_material_regression: bool = False
    no_unauthorized_files: bool = False
    no_authority_change: bool = False
    test_only_gaming: bool = False

    @property
    def accepted(self) -> bool:
        return (self.authority_ok and self.weakness_grounded and self.red_status is RedStatus.RED_CONFIRMED
                and self.focused_green and self.holdout_green and self.no_material_regression
                and self.no_unauthorized_files and self.no_authority_change and not self.test_only_gaming)

    def reasons(self) -> tuple[str, ...]:
        checks = (("authority", self.authority_ok), ("weakness_grounded", self.weakness_grounded),
                  ("red_valid", self.red_status is RedStatus.RED_CONFIRMED),
                  ("focused_green", self.focused_green), ("holdout_green", self.holdout_green),
                  ("no_material_regression", self.no_material_regression),
                  ("no_unauthorized_files", self.no_unauthorized_files), ("no_authority_change", self.no_authority_change),
                  ("no_test_gaming", not self.test_only_gaming))
        return tuple(name for name, value in checks if not value)


@dataclass(frozen=True)
class CampaignEvidence:
    """Immutable verifier output; attempt/provider score fields are excluded."""
    relevant_subsystem: bool
    red_status: RedStatus
    focused_green: bool
    holdout_green: bool
    no_material_regression: bool
    rejected_bad_candidate: bool = False
    repair_attempts: int = 0
    provider_failures: int = 0
    no_unauthorized_files: bool = False
    no_authority_change: bool = False
    test_only_gaming: bool = False
    mutation_provider: str = ""
    capability_before: float | None = None
    capability_after: float | None = None
    meta_before: float | None = None
    meta_after: float | None = None



def capability_score(*, evidence: CampaignEvidence | None = None, red: RedStatus | None = None,
                     focused_green: bool = False, holdout_green: bool = False,
                     no_regression: bool = False, attempts: int = 1) -> float:
    if evidence is not None:
        red, focused_green, holdout_green, no_regression = (
            evidence.red_status, evidence.focused_green, evidence.holdout_green,
            evidence.no_material_regression)
    values = [red is RedStatus.RED_CONFIRMED,
              focused_green, holdout_green, no_regression]
    return round(sum(values) / len(values), 6)


def meta_improvement_score(*, evidence: CampaignEvidence | None = None, relevant: bool = False,
                           genuine_red: bool = False, rejected_bad_candidate: bool = False,
                           attempts: int = 1, failures: int = 0) -> float:
    if evidence is not None:
        relevant, genuine_red, rejected_bad_candidate = (evidence.relevant_subsystem,
            evidence.red_status is RedStatus.RED_CONFIRMED, evidence.rejected_bad_candidate)
        attempts, failures = evidence.repair_attempts, evidence.provider_failures
    value = (int(relevant) + int(genuine_red) + int(rejected_bad_candidate)) / 3
    return round(max(0.0, value - 0.05 * max(0, attempts - 1) - 0.1 * failures), 6)


def evidence_level(accepted: int, capability_deltas: tuple[float, ...] = (), meta_deltas: tuple[float, ...] = ()) -> int:
    if accepted <= 0:
        return 0
    if accepted == 1:
        return 1
    if accepted < 3 or not capability_deltas or not any(delta > 0 for delta in capability_deltas):
        return 2
    positive_meta = sum(delta > 0 for delta in meta_deltas)
    if positive_meta < 2 or sum(meta_deltas) <= 0 or not meta_deltas or meta_deltas[-1] <= 0:
        return 3
    return 4


@dataclass
class Generation:
    generation: int
    weakness: Any
    hypothesis: str = ""
    provider: str = ""
    red: str = RedStatus.RED_UNAVAILABLE.value
    focused_green: bool = False
    holdout: bool = False
    score_before: float = 0.0
    score_after: float = 0.0
    delta: float = 0.0
    meta_score_before: float = 0.0
    meta_score_after: float = 0.0
    meta_delta: float = 0.0
    verdict: str = "REJECTED"
    rejection_reason: tuple[str, ...] = ()
    diff_fingerprint: str = ""
    changed_files: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    attempts: int = 1


@dataclass(frozen=True)
class CampaignResult:
    generations: tuple[Generation, ...]
    stop_reason: str
    accepted_generations: int
    evidence_level: int
    manifest_digest: str


def _fingerprint(outcome: Mapping[str, Any]) -> str:
    value = outcome.get("diff_fingerprint") or outcome.get("fingerprint") or outcome.get("changed_files", ())
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _write_ledger(root: Path, generation: Generation) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "ledger.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(generation), sort_keys=True, default=str) + "\n")


def run_campaign(*, weakness: Any, attempt: Callable[[int, Any], Mapping[str, Any]], max_generations: int = 1,
                 manifest: BenchmarkManifest | None = None, evidence_dir: str | Path | None = None,
                 verifier: Callable[[Mapping[str, Any], BenchmarkManifest], CampaignEvidence] | None = None) -> CampaignResult:
    """Run an explicit bounded campaign; only accepted state feeds the next attempt."""
    if not 1 <= max_generations <= MAX_GENERATIONS:
        raise ValueError(f"max_generations must be between 1 and {MAX_GENERATIONS}")
    manifest = manifest or BenchmarkManifest()
    digest = manifest.digest()
    root = Path(evidence_dir).resolve() if evidence_dir else None
    generations: list[Generation] = []
    accepted_state: Any = weakness
    fingerprints: set[str] = set()
    no_improvement = 0
    meta_plateau = 0
    capability_deltas: list[float] = []
    meta_deltas: list[float] = []
    for number in range(max_generations):
        if manifest.digest() != digest:
            return CampaignResult(tuple(generations), StopReason.TOOL_PROTOCOL_FAILURE.value, len([g for g in generations if g.verdict == "ACCEPTED"]), evidence_level(len([g for g in generations if g.verdict == "ACCEPTED"]), tuple(capability_deltas), tuple(meta_deltas)), digest)
        started = time.monotonic()
        try:
            outcome = dict(attempt(number, accepted_state))
        except PermissionError as error:
            outcome = {"authority_ok": False, "rejection_reason": (str(error),), "stop_reason": StopReason.AUTHORITY_VIOLATION.value}
        except Exception as error:
            outcome = {"authority_ok": True, "rejection_reason": (f"{type(error).__name__}: {error}",), "stop_reason": StopReason.TOOL_PROTOCOL_FAILURE.value}
        # The verifier is a host dependency, never an attribute of the attempt.
        trusted = CampaignEvidence(False, RedStatus.RED_UNAVAILABLE, False, False, False)
        if verifier is not None:
            try:
                measured = verifier(outcome, manifest)
                if type(measured) is not CampaignEvidence or manifest.digest() != digest:
                    raise ValueError("Invalid independent verifier evidence")
                trusted = measured
            except Exception:
                outcome["stop_reason"] = StopReason.TOOL_PROTOCOL_FAILURE.value
        provider = trusted.mutation_provider
        authority_ok = bool(provider) and verify_mutation_authority(provider)
        if outcome.get("provider") and not verify_mutation_authority(str(outcome["provider"])):
            outcome["stop_reason"] = StopReason.AUTHORITY_VIOLATION.value
            authority_ok = False
        red = trusted.red_status.value
        gate = CandidateGate(authority_ok, trusted.relevant_subsystem, trusted.red_status,
            trusted.focused_green, trusted.holdout_green, trusted.no_material_regression,
            trusted.no_unauthorized_files, trusted.no_authority_change, trusted.test_only_gaming)
        previous = next((item for item in reversed(generations) if item.verdict == "ACCEPTED"), None)

        # Mechanical RED/GREEN/holdout gates establish candidate validity,
        # not measurable capability improvement. Only the independent verifier
        # may supply benchmark measurements used to advance accepted state.
        measured_capability = (
            trusted.capability_before is not None
            and trusted.capability_after is not None
        )
        measured_meta = (
            trusted.meta_before is not None
            and trusted.meta_after is not None
        )

        before = float(trusted.capability_before) if measured_capability else (
            previous.score_after if previous else 0.0
        )
        after = float(trusted.capability_after) if measured_capability else before

        meta_before = float(trusted.meta_before) if measured_meta else (
            previous.meta_score_after if previous else 0.0
        )
        meta_after = float(trusted.meta_after) if measured_meta else meta_before

        delta, meta_delta = after - before, meta_after - meta_before
        fingerprint = _fingerprint(outcome)
        duplicate = fingerprint in fingerprints
        fingerprints.add(fingerprint)
        accepted = (
            gate.accepted
            and not duplicate
            and measured_capability
            and delta > 0
        )
        record = Generation(number, outcome.get("weakness", accepted_state), str(outcome.get("hypothesis", "")), provider, red,
                            gate.focused_green, gate.holdout_green, before, after, delta, meta_before, meta_after, meta_delta,
                            "ACCEPTED" if accepted else "REJECTED", tuple(outcome.get("rejection_reason", ())) or gate.reasons() or ((StopReason.CYCLING.value,) if duplicate else ()),
                            fingerprint, tuple(outcome.get("changed_files", ())), time.monotonic() - started, int(outcome.get("attempts", 1)))
        generations.append(record)
        if root:
            _write_ledger(root, record)
        if accepted:
            accepted_state = outcome.get("next_state", outcome.get("candidate", accepted_state))
            capability_deltas.append(delta)

            # Absence of an independent meta measurement is not evidence of a
            # meta plateau. Only measured meta results may advance plateau
            # accounting or contribute to meta-improvement evidence.
            if measured_meta:
                meta_deltas.append(meta_delta)
                meta_plateau = meta_plateau + 1 if meta_delta <= 0 else 0

            no_improvement = 0 if delta > 0 else no_improvement + 1
        else:
            no_improvement += 1
        if duplicate:
            stop = StopReason.CYCLING
            break
        stop_value = outcome.get("stop_reason")
        if stop_value:
            stop = StopReason(str(stop_value)) if str(stop_value) in StopReason._value2member_map_ else StopReason.TOOL_PROTOCOL_FAILURE
            break
        if no_improvement >= 3:
            stop = StopReason.PLATEAU
            break
        if meta_plateau >= 2:
            stop = StopReason.META_PLATEAU
            break
    else:
        stop = StopReason.MAX_GENERATIONS
    accepted_count = sum(item.verdict == "ACCEPTED" for item in generations)
    result = CampaignResult(tuple(generations), stop.value, accepted_count, evidence_level(accepted_count, tuple(capability_deltas), tuple(meta_deltas)), digest)
    if root:
        (root / "summary.json").write_text(json.dumps(asdict(result), sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result


__all__ = ["BenchmarkManifest", "BenchmarkChanged", "CandidateGate", "CampaignResult", "Generation", "MAX_GENERATIONS", "RedStatus", "StopReason", "capability_score", "classify_red", "evidence_level", "meta_improvement_score", "run_campaign"]
