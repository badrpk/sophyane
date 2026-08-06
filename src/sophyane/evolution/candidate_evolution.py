"""Evidence-grounded candidate evolution from recurrent principles.

Safety model:

1. Only recurrent principles are eligible.
2. Objective capability boundaries select the component.
3. Cloud analysis may generate a candidate diff.
4. The diff is restricted to one logical source component plus an optional
   regression test.
5. The diff is applied only inside a disposable Git worktree.
6. Representative failures are replayed against baseline and candidate.
7. Targeted tests and the full regression suite must pass.
8. Held-out performance cannot regress.
9. A passing candidate may be committed to an evolution/* branch.
10. This module never merges or pushes main.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .engine import COMPONENT_PATHS, EvolutionEngine
from .evidence_pipeline import EvidenceStore, LocalAnalyst
from .models import (
    EvolutionConfig,
    ExecutionTrace,
    PatchProposal,
    TaskSpec,
)
from .validators import validate


SOURCE_COMPONENT_PATHS: dict[str, tuple[str, ...]] = {
    "filesystem": (
        "src/sophyane/runtime_filesystem_capabilities_v20.py",
        "src/sophyane/capability_executors.py",
        "src/sophyane/execution_runtime.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "python": (
        "src/sophyane/capability_executors.py",
        "src/sophyane/local_coding_capability.py",
        "src/sophyane/execution_runtime.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "html": (
        "src/sophyane/code_memory/",
        "src/sophyane/local_site_refinement.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "shell": (
        "src/sophyane/execution_runtime.py",
        "src/sophyane/capability_executors.py",
        "src/sophyane/sli_chunk_router.py",
        "src/sophyane/tui_v2.py",
    ),
    "security": (
        "src/sophyane/security/",
        "src/sophyane/harness_task_policy.py",
        "src/sophyane/capability_executors.py",
        "src/sophyane/tui_v2.py",
    ),
    "semantic_router": (
        "src/sophyane/semantic_intent_router.py",
        "src/sophyane/personal_fact_resolver.py",
        "src/sophyane/sli_personal_connector.py",
        "src/sophyane/tui_v2.py",
    ),
}

COMPONENT_CAPABILITY = {
    "filesystem": "filesystem",
    "python": "python",
    "html": "html",
    "shell": "shell",
    "security": "security",
    "semantic_router": "semantic_routing",
}

MAX_SOURCE_FILES = 1
MAX_TEST_FILES = 1
MAX_CHANGED_LINES = 300


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _json_object(value: str) -> dict[str, Any]:
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        str(value or "").strip(),
        flags=re.I,
    )
    text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start < 0 or end <= start:
        raise ValueError("No JSON object returned")

    return json.loads(text[start : end + 1])


def _candidate_payload(
    value: str,
    *,
    component: str,
) -> dict[str, Any]:
    """Recover a candidate from JSON or a model-produced diff block.

    Unified diffs contain many quotes and literal newlines, so models
    frequently return a valid diff inside Markdown while failing to encode
    it as a valid JSON string. The diff remains subject to all normal path,
    size, security, application and regression gates.
    """
    raw = str(value or "").strip()

    if not raw:
        raise ValueError(
            "Gemini returned an empty candidate response"
        )

    try:
        payload = _json_object(raw)

        if str(payload.get("patch") or "").strip():
            return payload
    except (
        ValueError,
        json.JSONDecodeError,
    ):
        pass

    fenced = re.search(
        r"```diff\s*"
        r"(diff --git\s+.+?)"
        r"(?:```|\Z)",
        raw,
        flags=re.I | re.S,
    )

    if fenced:
        patch = fenced.group(1).strip()
    else:
        start = raw.find("diff --git ")

        if start < 0:
            raise ValueError(
                "Gemini response contained neither valid JSON "
                "nor a unified Git diff"
            )

        patch = raw[start:].strip()

    tests = [
        item
        for item in _diff_paths(patch)
        if item.startswith("tests/")
    ]

    rationale_text = re.sub(
        r"```diff.*",
        "",
        raw,
        flags=re.I | re.S,
    )

    rationale = " ".join(
        rationale_text.split()
    )[:1200]

    return {
        "component": component,
        "rationale": (
            rationale
            or "Recovered unified diff from Gemini response."
        ),
        "patch": patch,
        "tests": tests,
        "confidence": 0.70,
        "response_format_recovered": True,
    }


def _diff_paths(patch: str) -> list[str]:
    paths = re.findall(
        r"^\+\+\+\s+b/(.+)$",
        patch,
        flags=re.M,
    )

    return [
        path.strip()
        for path in paths
        if path.strip() != "/dev/null"
    ]


def _changed_lines(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if (
            line.startswith("+")
            or line.startswith("-")
        )
        and not line.startswith(("+++", "---"))
    )


def _path_allowed(
    path: str,
    allowed: tuple[str, ...],
) -> bool:
    return any(
        path == item
        or path.startswith(
            item.rstrip("/") + "/"
        )
        for item in allowed
    )


@dataclass
class ReplayResult:
    task_id: str
    capability: str
    passed: bool
    checks: dict[str, bool]
    errors: list[str]
    stdout_tail: str = ""
    stderr_tail: str = ""


@dataclass
class CandidateEvaluation:
    candidate_id: str
    component: str
    capability: str
    principle_id: str
    principle: str
    branch: str
    worktree: str
    proposal: dict[str, Any]
    baseline_replays: list[ReplayResult]
    candidate_replays: list[ReplayResult]
    baseline_score: float
    candidate_score: float
    representative_improved: bool
    targeted_tests_passed: bool
    full_suite_passed: bool
    held_out_baseline_score: float
    held_out_candidate_score: float
    held_out_not_regressed: bool
    security_gate_passed: bool
    promotable: bool
    committed: bool
    status: str
    details: dict[str, Any] = field(default_factory=dict)

    def write(self, root: Path) -> Path:
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            root
            / f"{self.candidate_id}.json"
        )

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


class CandidateEvolver:
    def __init__(
        self,
        repo: Path,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.store = EvidenceStore(self.repo)
        self.engine = EvolutionEngine(
            EvolutionConfig(
                repo=self.repo,
                allow_cloud_analysis=True,
                allow_candidate_patches=False,
                allow_promotion=False,
            )
        )
        self.local = LocalAnalyst()

        self.root = (
            self.repo
            / ".sophyane-evolution"
        )
        self.worktrees = (
            self.root
            / "worktrees"
        )
        self.candidates = (
            self.root
            / "candidates"
        )

        self.worktrees.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.candidates.mkdir(
            parents=True,
            exist_ok=True,
        )

    def cloud_available(self) -> bool:
        return bool(
            self.engine._gemini_key()
        )

    def recurrent_principles(
        self,
        *,
        component: str = "",
    ) -> list[dict[str, Any]]:
        return (
            self.store.principles
            .recurrent_principles(
                component=component,
            )
        )

    def select_principle(
        self,
        *,
        component: str = "",
    ) -> dict[str, Any]:
        principles = self.recurrent_principles(
            component=component,
        )

        if not principles:
            raise RuntimeError(
                "No recurrent principle is available "
                f"for component {component or '(any)'}."
            )

        preferred = {
            "python": 0,
            "filesystem": 1,
            "html": 2,
            "shell": 3,
            "semantic_router": 4,
            "security": 5,
        }

        principles.sort(
            key=lambda item: (
                preferred.get(
                    str(item.get("component")),
                    99,
                ),
                -len(
                    item.get(
                        "distinct_tasks",
                        [],
                    )
                ),
                -float(
                    item.get(
                        "maximum_confidence",
                        0.0,
                    )
                ),
            )
        )

        return principles[0]

    def representative_records(
        self,
        *,
        component: str,
        limit: int = 3,
    ) -> list[tuple[Path, dict[str, Any]]]:
        capability = COMPONENT_CAPABILITY[
            component
        ]

        selected: list[
            tuple[Path, dict[str, Any]]
        ] = []

        for path in self.store.record_paths():
            data = self.store.read(path)

            if (
                data.get("task", {}).get(
                    "capability"
                )
                != capability
            ):
                continue

            if data.get(
                "validation",
                {},
            ).get("passed"):
                continue

            selected.append((path, data))

        # Prefer failures with different task text.
        unique: list[
            tuple[Path, dict[str, Any]]
        ] = []
        seen_prompts: set[str] = set()

        for item in selected:
            prompt = " ".join(
                str(
                    item[1]
                    .get("task", {})
                    .get("prompt")
                    or ""
                ).casefold().split()
            )

            if prompt in seen_prompts:
                continue

            seen_prompts.add(prompt)
            unique.append(item)

            if len(unique) >= limit:
                break

        if len(unique) < limit:
            for item in selected:
                if item in unique:
                    continue

                unique.append(item)

                if len(unique) >= limit:
                    break

        return unique

    def _source_context(
        self,
        *,
        component: str,
    ) -> str:
        allowed = SOURCE_COMPONENT_PATHS[
            component
        ]

        parts: list[str] = []

        for item in allowed:
            path = self.repo / item

            if path.is_file():
                text = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                parts.append(
                    f"\n===== {item} =====\n"
                    + text[:18_000]
                )

                continue

            if path.is_dir():
                for child in sorted(
                    path.rglob("*.py")
                )[:6]:
                    relative = str(
                        child.relative_to(
                            self.repo
                        )
                    )

                    text = child.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    parts.append(
                        f"\n===== {relative} =====\n"
                        + text[:10_000]
                    )

        return "\n".join(parts)[
            :50_000
        ]

    def _representative_context(
        self,
        records: list[
            tuple[Path, dict[str, Any]]
        ],
    ) -> str:
        payload = []

        for path, data in records:
            analysis = (
                data.get(
                    "analysis_pipeline"
                )
                or {}
            )

            payload.append(
                {
                    "record": path.name,
                    "task": data.get("task"),
                    "validation": data.get(
                        "validation"
                    ),
                    "trace": {
                        "exit_code": (
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "exit_code"
                            )
                        ),
                        "files": (
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "files"
                            )
                        ),
                        "stdout_tail": str(
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "stdout"
                            )
                            or ""
                        )[-2500:],
                        "stderr_tail": str(
                            data.get(
                                "trace",
                                {},
                            ).get(
                                "stderr"
                            )
                            or ""
                        )[-1500:],
                    },
                    "final_analysis": (
                        analysis.get("final")
                    ),
                    "arbitration": (
                        analysis.get(
                            "arbitration"
                        )
                    ),
                }
            )

        return json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )

    def _local_patch_critique(
        self,
        proposal: PatchProposal,
        *,
        principle: str,
    ) -> dict[str, Any]:
        if not self.local.available():
            return {
                "available": False,
                "accepted": True,
                "reason": (
                    "Local analyst unavailable; "
                    "objective gates remain authoritative."
                ),
            }

        prompt = f"""
Review this candidate patch conservatively.

The patch must implement a reusable harness improvement for this principle:

{principle}

It may modify one source component and one regression test only.
Reject:
- exact-prompt hardcoding;
- exact benchmark filenames or answers in production routing;
- security weakening;
- bypassing validators;
- broad unrelated rewrites.

Return JSON only:
{{
  "accepted": true,
  "reason": "...",
  "risks": ["..."]
}}

Patch:
{proposal.patch}
"""

        try:
            raw = self.local.analyze(
                {
                    "task": {
                        "prompt": prompt,
                        "capability": (
                            COMPONENT_CAPABILITY[
                                proposal.component
                            ]
                        ),
                    },
                    "trace": {
                        "exit_code": 0,
                        "stdout": proposal.patch,
                        "stderr": "",
                        "files": _diff_paths(
                            proposal.patch
                        ),
                    },
                }
            )

            if raw is None:
                return {
                    "available": True,
                    "accepted": True,
                    "reason": (
                        "Local analyst returned no "
                        "structured critique."
                    ),
                }

            lowered = (
                raw.summary
                + " "
                + raw.general_principle
            ).casefold()

            rejected = any(
                term in lowered
                for term in (
                    "reject",
                    "unsafe",
                    "hardcode",
                    "bypass",
                    "unrelated",
                )
            )

            return {
                "available": True,
                "accepted": not rejected,
                "reason": raw.summary,
                "evidence": raw.evidence,
            }

        except Exception as error:
            return {
                "available": True,
                "accepted": True,
                "reason": (
                    "Local critique failed safely: "
                    f"{type(error).__name__}: {error}"
                ),
            }

    def _save_raw_candidate_response(
        self,
        *,
        component: str,
        stage: str,
        response: str,
    ) -> Path:
        """Preserve model output without exposing credentials."""
        root = (
            self.root
            / "raw-proposals"
        )
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            root
            / (
                component
                + "-"
                + time.strftime(
                    "%Y%m%d-%H%M%S"
                )
                + "-"
                + stage
                + ".txt"
            )
        )

        path.write_text(
            str(response or ""),
            encoding="utf-8",
        )

        return path

    def generate_proposal(
        self,
        *,
        principle_item: dict[str, Any],
        records: list[
            tuple[Path, dict[str, Any]]
        ],
    ) -> PatchProposal:
        if not self.cloud_available():
            raise RuntimeError(
                "Cloud analyst is unavailable. "
                "A Gemini key is required for candidate generation."
            )

        component = str(
            principle_item["component"]
        )

        allowed = SOURCE_COMPONENT_PATHS[
            component
        ]

        source_context = self._source_context(
            component=component,
        )

        records_context = (
            self._representative_context(
                records
            )
        )

        prompt = f"""
You are generating one constrained candidate patch for Sophyane.

Objective component:
{component}

Recurrent principle:
{principle_item["principle"]}

Distinct supporting failures:
{len(principle_item.get("distinct_tasks", []))}

Allowed production paths:
{json.dumps(allowed)}

Patch constraints:
- Modify at most one production source file.
- Optionally modify or create one regression test under tests/.
- Do not change any other file.
- Do not weaken security or validators.
- Do not alter tests merely to hide failure.
- Do not hardcode exact benchmark wording, expected literal output, or one
  benchmark filename into a general route.
- Preserve Option 2 strict local-only policy.
- Preserve private/public semantic boundaries.
- Maximum changed lines: {MAX_CHANGED_LINES}.
- Return a valid unified Git diff.
- Include a test that proves reusable behavior.

Representative failures:
{records_context}

Relevant current source:
{source_context}

Return JSON only:
{{
  "component": "{component}",
  "rationale": "...",
  "patch": "diff --git ...",
  "tests": ["tests/path_to_test.py"],
  "confidence": 0.0
}}
"""

        raw_response = self.engine._gemini(
            prompt
        )

        raw_path = (
            self._save_raw_candidate_response(
                component=component,
                stage="initial",
                response=raw_response,
            )
        )

        try:
            parsed = _candidate_payload(
                raw_response,
                component=component,
            )
        except ValueError as first_error:
            repair_prompt = f"""
Reformat the candidate below without changing its intended code change.

Return either:

1. Valid JSON with keys component, rationale, patch, tests and confidence;
   the patch value must contain the complete unified Git diff.

or, if valid JSON escaping is difficult:

2. A short rationale followed by exactly one fenced ```diff block.

Do not add a second patch. Do not broaden the change. Do not omit diff
headers.

Required component:
{component}

Original response:
{raw_response[-16000:]}
"""

            repaired_response = (
                self.engine._gemini(
                    repair_prompt
                )
            )

            repaired_path = (
                self._save_raw_candidate_response(
                    component=component,
                    stage="repair",
                    response=repaired_response,
                )
            )

            try:
                parsed = _candidate_payload(
                    repaired_response,
                    component=component,
                )
            except ValueError as repair_error:
                raise ValueError(
                    "Gemini candidate formatting failed after one "
                    "repair attempt. "
                    f"Initial response: {raw_path}. "
                    f"Repair response: {repaired_path}. "
                    f"Initial error: {first_error}. "
                    f"Repair error: {repair_error}."
                ) from repair_error

        proposal = PatchProposal(
            component=component,
            rationale=str(
                parsed.get("rationale")
                or ""
            ),
            patch=str(
                parsed.get("patch")
                or ""
            ),
            tests=[
                str(item)
                for item in (
                    parsed.get("tests")
                    or []
                )
                if str(item).strip()
            ],
            confidence=float(
                parsed.get("confidence")
                or 0.0
            ),
            allowed_paths=list(allowed),
        )

        self.validate_proposal(
            proposal
        )

        return proposal

    def validate_proposal(
        self,
        proposal: PatchProposal,
    ) -> None:
        if proposal.component not in (
            SOURCE_COMPONENT_PATHS
        ):
            raise ValueError(
                "Unknown proposal component"
            )

        if not proposal.patch.startswith(
            "diff --git "
        ):
            raise ValueError(
                "Proposal did not contain a unified Git diff"
            )

        paths = _diff_paths(
            proposal.patch
        )

        if not paths:
            raise ValueError(
                "Candidate patch modifies no files"
            )

        source_paths = [
            path
            for path in paths
            if path.startswith("src/")
        ]

        test_paths = [
            path
            for path in paths
            if path.startswith("tests/")
        ]

        other_paths = [
            path
            for path in paths
            if (
                path not in source_paths
                and path not in test_paths
            )
        ]

        if other_paths:
            raise ValueError(
                "Candidate modifies forbidden paths: "
                + ", ".join(other_paths)
            )

        if (
            not source_paths
            or len(set(source_paths))
            > MAX_SOURCE_FILES
        ):
            raise ValueError(
                "Candidate must modify exactly one "
                "production source file"
            )

        if (
            len(set(test_paths))
            > MAX_TEST_FILES
        ):
            raise ValueError(
                "Candidate may modify at most one test file"
            )

        allowed = SOURCE_COMPONENT_PATHS[
            proposal.component
        ]

        for path in source_paths:
            if not _path_allowed(
                path,
                allowed,
            ):
                raise ValueError(
                    "Candidate source path is outside "
                    f"component boundary: {path}"
                )

        if _changed_lines(
            proposal.patch
        ) > MAX_CHANGED_LINES:
            raise ValueError(
                "Candidate patch is too large"
            )

        lowered = proposal.patch.casefold()

        forbidden = (
            "disable security",
            "skip validation",
            "always return true",
            "pytest.skip",
            "@pytest.mark.skip",
            "public internet fallback: allowed",
            "sophyane_disable_cloud_fallback=0",
            "/etc/shadow",
        )

        for term in forbidden:
            if term in lowered:
                raise ValueError(
                    "Forbidden candidate content: "
                    + term
                )

    def _runtime_command(
        self,
        *,
        source_repo: Path,
    ) -> tuple[list[str], dict[str, str]]:
        python = (
            self.repo
            / ".venv"
            / "bin"
            / "python"
        )

        command = [
            str(python),
            "-m",
            "sophyane.tui_v2",
        ]

        env = os.environ.copy()

        candidate_src = str(
            source_repo / "src"
        )

        existing = env.get(
            "PYTHONPATH",
            "",
        )

        env["PYTHONPATH"] = (
            candidate_src
            if not existing
            else candidate_src
            + os.pathsep
            + existing
        )

        env.update(
            {
                "SOPHYANE_SESSION_MODE": "sli_chunks",
                "SOPHYANE_SLI_ONLY": "1",
                "SOPHYANE_NO_BROWSER": "1",
                "SOPHYANE_DISABLE_GOAL_DIALOGUE": "1",
            }
        )

        return command, env

    def replay_task(
        self,
        *,
        source_repo: Path,
        task: TaskSpec,
    ) -> ReplayResult:
        workspace = Path(
            tempfile.mkdtemp(
                prefix=(
                    "sophyane-candidate-replay-"
                    + task.task_id
                    + "-"
                )
            )
        )

        command, env = self._runtime_command(
            source_repo=source_repo,
        )

        try:
            result = subprocess.run(
                command,
                input=task.prompt + "\nexit\n",
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )

            files = [
                str(
                    path.relative_to(
                        workspace
                    )
                )
                for path in workspace.rglob("*")
                if path.is_file()
            ]

            trace = ExecutionTrace(
                task_id=task.task_id,
                workspace=str(workspace),
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                elapsed_seconds=0.0,
                files=files,
            )

            verdict = validate(
                task,
                trace,
            )

            return ReplayResult(
                task_id=task.task_id,
                capability=task.capability,
                passed=verdict.passed,
                checks=verdict.checks,
                errors=verdict.errors,
                stdout_tail=(
                    result.stdout[-2500:]
                ),
                stderr_tail=(
                    result.stderr[-1500:]
                ),
            )

        except subprocess.TimeoutExpired:
            return ReplayResult(
                task_id=task.task_id,
                capability=task.capability,
                passed=False,
                checks={
                    "timeout": False,
                },
                errors=[
                    "candidate replay timed out",
                ],
            )

        finally:
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )

    @staticmethod
    def _task_from_record(
        data: dict[str, Any],
    ) -> TaskSpec:
        task = data.get("task") or {}

        return TaskSpec(
            task_id=str(
                task.get("task_id")
                or "representative"
            ),
            prompt=str(
                task.get("prompt")
                or ""
            ),
            capability=str(
                task.get("capability")
                or ""
            ),
            validator=str(
                task.get("validator")
                or task.get("capability")
                or ""
            ),
            expected=(
                task.get("expected")
                if isinstance(
                    task.get("expected"),
                    dict,
                )
                else {}
            ),
            held_out=bool(
                task.get("held_out")
            ),
        )

    def replay_records(
        self,
        *,
        source_repo: Path,
        records: list[
            tuple[Path, dict[str, Any]]
        ],
    ) -> list[ReplayResult]:
        return [
            self.replay_task(
                source_repo=source_repo,
                task=self._task_from_record(
                    data
                ),
            )
            for _path, data in records
        ]

    def held_out_tasks(
        self,
        *,
        capability: str,
    ) -> list[TaskSpec]:
        tasks = list(
            self.engine
            ._generalization_tasks(
                capability
            )
        )

        extra: dict[
            str,
            list[TaskSpec],
        ] = {
            "filesystem": [
                TaskSpec(
                    task_id=(
                        "heldout-filesystem-exact"
                    ),
                    prompt=(
                        "Create verify.txt containing exactly "
                        "VERIFIED and verify its exact bytes."
                    ),
                    capability="filesystem",
                    validator="filesystem",
                    held_out=True,
                )
            ],
            "python": [
                TaskSpec(
                    task_id=(
                        "heldout-python-function"
                    ),
                    prompt=(
                        "Create math_probe.py with multiply(a, b), "
                        "create a pytest proving multiply(6, 7) "
                        "equals 42, and run the test."
                    ),
                    capability="python",
                    validator="python",
                    held_out=True,
                )
            ],
        }

        tasks.extend(
            extra.get(
                capability,
                [],
            )
        )

        return tasks

    def replay_tasks(
        self,
        *,
        source_repo: Path,
        tasks: list[TaskSpec],
    ) -> list[ReplayResult]:
        return [
            self.replay_task(
                source_repo=source_repo,
                task=task,
            )
            for task in tasks
        ]

    @staticmethod
    def score(
        results: list[ReplayResult],
    ) -> float:
        if not results:
            return 1.0

        return sum(
            1
            for item in results
            if item.passed
        ) / len(results)

    def _create_worktree(
        self,
        candidate_id: str,
    ) -> tuple[Path, str]:
        worktree = (
            self.worktrees
            / candidate_id
        )

        branch = (
            "evolution/"
            + candidate_id
        )

        if worktree.exists():
            raise RuntimeError(
                f"Worktree already exists: {worktree}"
            )

        result = subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree),
                "HEAD",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Could not create candidate worktree:\n"
                + result.stdout
                + result.stderr
            )

        return worktree, branch

    def _apply_patch(
        self,
        *,
        worktree: Path,
        patch: str,
    ) -> None:
        patch_file = (
            worktree
            / ".sophyane-candidate.patch"
        )

        patch_file.write_text(
            patch,
            encoding="utf-8",
        )

        check = subprocess.run(
            [
                "git",
                "apply",
                "--check",
                str(patch_file),
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )

        if check.returncode != 0:
            raise RuntimeError(
                "Candidate patch does not apply:\n"
                + check.stdout
                + check.stderr
            )

        subprocess.run(
            [
                "git",
                "apply",
                str(patch_file),
            ],
            cwd=worktree,
            check=True,
        )

        patch_file.unlink(
            missing_ok=True
        )

    def _targeted_tests(
        self,
        *,
        worktree: Path,
        proposal: PatchProposal,
    ) -> tuple[bool, str]:
        test_paths = [
            path
            for path in _diff_paths(
                proposal.patch
            )
            if path.startswith("tests/")
        ]

        python = (
            self.repo
            / ".venv"
            / "bin"
            / "python"
        )

        if test_paths:
            command = [
                str(python),
                "-m",
                "pytest",
                "-q",
                *test_paths,
            ]
        else:
            source_paths = [
                path
                for path in _diff_paths(
                    proposal.patch
                )
                if (
                    path.startswith("src/")
                    and path.endswith(".py")
                )
            ]

            command = [
                str(python),
                "-m",
                "py_compile",
                *source_paths,
            ]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(
            worktree / "src"
        )

        result = subprocess.run(
            command,
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            timeout=360,
            check=False,
        )

        return (
            result.returncode == 0,
            result.stdout[-4000:]
            + result.stderr[-4000:],
        )

    def _full_suite(
        self,
        *,
        worktree: Path,
    ) -> tuple[bool, str]:
        python = (
            self.repo
            / ".venv"
            / "bin"
            / "python"
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = str(
            worktree / "src"
        )

        result = subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "-q",
            ],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            timeout=1200,
            check=False,
        )

        return (
            result.returncode == 0,
            result.stdout[-6000:]
            + result.stderr[-6000:],
        )

    def evolve(
        self,
        *,
        component: str = "",
        representative_limit: int = 3,
        commit_candidate: bool = False,
    ) -> CandidateEvaluation:
        principle_item = (
            self.select_principle(
                component=component,
            )
        )

        component = str(
            principle_item["component"]
        )

        capability = COMPONENT_CAPABILITY[
            component
        ]

        records = (
            self.representative_records(
                component=component,
                limit=representative_limit,
            )
        )

        if not records:
            raise RuntimeError(
                "No representative failed records "
                f"exist for {component}."
            )

        proposal = self.generate_proposal(
            principle_item=principle_item,
            records=records,
        )

        local_critique = (
            self._local_patch_critique(
                proposal,
                principle=str(
                    principle_item[
                        "principle"
                    ]
                ),
            )
        )

        if not local_critique.get(
            "accepted",
            True,
        ):
            raise RuntimeError(
                "Local analyst rejected candidate: "
                + str(
                    local_critique.get(
                        "reason"
                    )
                )
            )

        candidate_id = (
            component
            + "-"
            + time.strftime(
                "%Y%m%d-%H%M%S"
            )
        )

        worktree, branch = (
            self._create_worktree(
                candidate_id
            )
        )

        self._apply_patch(
            worktree=worktree,
            patch=proposal.patch,
        )

        baseline_replays = (
            self.replay_records(
                source_repo=self.repo,
                records=records,
            )
        )

        candidate_replays = (
            self.replay_records(
                source_repo=worktree,
                records=records,
            )
        )

        baseline_score = self.score(
            baseline_replays
        )

        candidate_score = self.score(
            candidate_replays
        )

        representative_improved = (
            candidate_score
            > baseline_score
            and any(
                candidate.passed
                and not baseline.passed
                for baseline, candidate
                in zip(
                    baseline_replays,
                    candidate_replays,
                )
            )
        )

        held_out_tasks = (
            self.held_out_tasks(
                capability=capability,
            )
        )

        baseline_held_out = (
            self.replay_tasks(
                source_repo=self.repo,
                tasks=held_out_tasks,
            )
        )

        candidate_held_out = (
            self.replay_tasks(
                source_repo=worktree,
                tasks=held_out_tasks,
            )
        )

        held_out_baseline_score = (
            self.score(
                baseline_held_out
            )
        )

        held_out_candidate_score = (
            self.score(
                candidate_held_out
            )
        )

        held_out_not_regressed = (
            held_out_candidate_score
            >= held_out_baseline_score
        )

        (
            targeted_tests_passed,
            targeted_output,
        ) = self._targeted_tests(
            worktree=worktree,
            proposal=proposal,
        )

        (
            full_suite_passed,
            full_suite_output,
        ) = self._full_suite(
            worktree=worktree,
        )

        security_gate_passed = (
            full_suite_passed
            and not any(
                term in proposal.patch.casefold()
                for term in (
                    "disable security",
                    "skip validation",
                    "/etc/shadow",
                    "@pytest.mark.skip",
                )
            )
        )

        promotable = all(
            (
                proposal.confidence
                >= 0.65,
                representative_improved,
                targeted_tests_passed,
                full_suite_passed,
                held_out_not_regressed,
                security_gate_passed,
            )
        )

        committed = False

        if (
            promotable
            and commit_candidate
        ):
            subprocess.run(
                [
                    "git",
                    "add",
                    "-A",
                ],
                cwd=worktree,
                check=True,
            )

            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    (
                        "Candidate evolution: "
                        + component
                    ),
                ],
                cwd=worktree,
                check=True,
            )

            committed = True

        status = (
            "candidate_committed"
            if committed
            else "candidate_promotable"
            if promotable
            else "candidate_rejected"
        )

        result = CandidateEvaluation(
            candidate_id=candidate_id,
            component=component,
            capability=capability,
            principle_id=str(
                principle_item["id"]
            ),
            principle=str(
                principle_item[
                    "principle"
                ]
            ),
            branch=branch,
            worktree=str(worktree),
            proposal=asdict(proposal),
            baseline_replays=(
                baseline_replays
            ),
            candidate_replays=(
                candidate_replays
            ),
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            representative_improved=(
                representative_improved
            ),
            targeted_tests_passed=(
                targeted_tests_passed
            ),
            full_suite_passed=(
                full_suite_passed
            ),
            held_out_baseline_score=(
                held_out_baseline_score
            ),
            held_out_candidate_score=(
                held_out_candidate_score
            ),
            held_out_not_regressed=(
                held_out_not_regressed
            ),
            security_gate_passed=(
                security_gate_passed
            ),
            promotable=promotable,
            committed=committed,
            status=status,
            details={
                "created_at": _now(),
                "representative_records": [
                    path.name
                    for path, _data
                    in records
                ],
                "local_patch_critique": (
                    local_critique
                ),
                "targeted_output": (
                    targeted_output
                ),
                "full_suite_output": (
                    full_suite_output
                ),
                "baseline_held_out": [
                    asdict(item)
                    for item
                    in baseline_held_out
                ],
                "candidate_held_out": [
                    asdict(item)
                    for item
                    in candidate_held_out
                ],
                "main_modified": False,
                "main_merged": False,
                "remote_pushed": False,
            },
        )

        result.write(
            self.candidates
        )

        return result
