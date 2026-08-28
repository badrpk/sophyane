"""Structured shared state for harness evolution."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TaskSpec:
    task_id: str
    prompt: str
    capability: str
    validator: str
    expected: dict[str, Any] = field(
        default_factory=dict
    )
    held_out: bool = False


@dataclass
class ExecutionTrace:
    task_id: str
    workspace: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    files: list[str] = field(
        default_factory=list
    )


@dataclass
class ValidationResult:
    passed: bool
    validator: str
    checks: dict[str, bool]
    errors: list[str] = field(
        default_factory=list
    )


@dataclass
class FeedbackReport:
    kind: str
    author: str
    summary: str
    evidence: list[str] = field(
        default_factory=list
    )
    suspected_component: str = ""
    confidence: float = 0.0
    mismatch: str = ""
    general_principle: str = ""


@dataclass
class PatchProposal:
    component: str
    rationale: str
    patch: str
    tests: list[str]
    confidence: float
    allowed_paths: list[str]


@dataclass
class GateResult:
    targeted_passed: bool
    regression_passed: bool
    held_out_passed: bool
    baseline_score: float
    candidate_score: float
    security_passed: bool
    promotable: bool
    details: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class EvolutionRecord:
    run_id: str
    cycle: int
    task: TaskSpec
    trace: ExecutionTrace
    validation: ValidationResult
    blind_report: FeedbackReport | None = None
    hindsight_report: FeedbackReport | None = None
    proposal: PatchProposal | None = None
    gate: GateResult | None = None

    # RED_QUEEN_ENGINE_ATTRIBUTION_V1
    #
    # These fields are deliberately defaulted so historical EvolutionRecord
    # construction and previously serialized record consumers remain
    # compatible. They describe evaluator authority; they do not replace
    # the existing targeted/regression/held-out/security GateResult.
    evaluator_id: str = ""
    evaluator_version: int = 0
    evaluator_identity: str = ""
    evaluator_epoch: int = 0
    evaluator_promotion_accepted: bool = False
    evaluator_promotion_reason: str = ""
    trusted_anchor_score: float | None = None

    status: str = "observed"
    created_at: float = field(
        default_factory=time.time
    )

    def write(self, root: Path) -> Path:
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = root / f"{self.run_id}.json"

        path.write_text(
            json.dumps(
                asdict(self),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        return path


@dataclass
class EvolutionConfig:
    repo: Path
    target_name: str = "sophyane"
    target_repo: Path | None = None
    badrpk_root: Path | None = None
    cycles: int = 1
    timeout_seconds: int = 180
    allow_cloud_analysis: bool = True
    allow_candidate_patches: bool = False
    allow_promotion: bool = False
    max_patch_files: int = 1
    max_patch_lines: int = 250
    mastery_threshold: float = 0.90
    minimum_mastery_samples: int = 20
    focus_window: int = 25
    principle_recurrence_required: int = 2
    full_test_command: tuple[str, ...] = (
        "python",
        "-m",
        "pytest",
        "-q",
    )
    records_dir: Path | None = None

    def resolved_records_dir(self) -> Path:
        return (
            self.records_dir
            or self.repo
            / ".sophyane-evolution"
            / "records"
        )


def new_run_id() -> str:
    return (
        time.strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
    )
