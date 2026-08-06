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
    cycles: int = 1
    timeout_seconds: int = 180
    allow_cloud_analysis: bool = True
    allow_candidate_patches: bool = False
    allow_promotion: bool = False
    max_patch_files: int = 1
    max_patch_lines: int = 250
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
