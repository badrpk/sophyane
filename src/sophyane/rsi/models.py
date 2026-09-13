"""Small JSON-friendly evidence records (commands are argv tuples)."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeaknessRecord:
    weakness_id: str
    description: str
    evidence: tuple[str, ...]
    baseline_commit: str
    target_metric: str
    baseline_value: float
    required_improvement: float
    protected_metrics: dict[str, dict]
    verification_commands: tuple[tuple[str, ...], ...]
    direction: str = 'higher'


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reasons: tuple[str, ...]
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BaselineRecord:
    commit: str
    repository: str
    repository_identity: str
    clean_state: bool
    worktree_state: str
    metrics: dict[str, float]
    tests: dict
    authority: tuple[str, ...]


@dataclass
class CandidateRecord:
    candidate_id: str
    baseline_commit: str
    name: str
    worktree_path: str
    provider_used: str = ''
    source_mutation_authority: bool = False
    candidate_commit: str | None = None


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    output: str
    cwd: str = ''

    @property
    def digest(self):
        import hashlib
        return hashlib.sha256(self.output.encode()).hexdigest()


@dataclass(frozen=True)
class VerificationResult:
    red: CommandResult | None = None
    green: tuple[CommandResult, ...] = ()
    expected_failure: str = ''
    targeted: tuple[CommandResult, ...] = ()
    subsystem: tuple[CommandResult, ...] = ()
    full_regression: tuple[CommandResult, ...] = ()
    static_checks: tuple[CommandResult, ...] = ()
    authority: bool = False
    isolation: bool = False
    benchmark: bool = False
    protected_metrics: bool = False
    post_promotion_smoke: tuple[CommandResult, ...] = ()


from enum import Enum


class IterationState(str, Enum):
    NO_ACTION = 'NO_ACTION'
    DETECTED = 'DETECTED'
    BASELINED = 'BASELINED'
    CANDIDATE_CREATED = 'CANDIDATE_CREATED'
    RED_CONFIRMED = 'RED_CONFIRMED'
    MODIFYING = 'MODIFYING'
    VERIFYING = 'VERIFYING'
    REJECTED = 'REJECTED'
    DEFERRED_NO_CODING_PROVIDER = 'DEFERRED_NO_CODING_PROVIDER'
    PROMOTION_READY = 'PROMOTION_READY'
    PROMOTING = 'PROMOTING'
    PROMOTED = 'PROMOTED'
    ROLLED_BACK = 'ROLLED_BACK'
    VERIFIED_BASELINE = 'VERIFIED_BASELINE'
    CANCELLED = 'CANCELLED'


@dataclass(frozen=True)
class IterationResult:
    iteration_id: str
    state: IterationState
    evidence: dict = field(default_factory=dict)
