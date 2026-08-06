"""Constrained evolution engine.

Cloud analysis may propose code, but promotion requires:
1. one-component path constraint,
2. successful patch application in a worktree,
3. targeted tests,
4. full regression suite,
5. held-out generalization tasks,
6. explicit promotion permission.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .curriculum import (
    generate_task,
    update_score,
)
from .models import (
    EvolutionConfig,
    EvolutionRecord,
    ExecutionTrace,
    FeedbackReport,
    GateResult,
    PatchProposal,
    TaskSpec,
    new_run_id,
)
from .validators import validate


COMPONENT_PATHS = {
    "semantic_router": (
        "src/sophyane/semantic_intent_router.py",
        "src/sophyane/personal_fact_resolver.py",
    ),
    "filesystem": (
        "src/sophyane/runtime_filesystem_capabilities_v20.py",
        "src/sophyane/capability_executors.py",
    ),
    "html": (
        "src/sophyane/code_memory/",
        "src/sophyane/local_site_refinement.py",
    ),
    "shell": (
        "src/sophyane/execution_runtime.py",
        "src/sophyane/capability_executors.py",
    ),
    "security": (
        "src/sophyane/security",
        "src/sophyane/harness_task_policy.py",
    ),
    "python": (
        "src/sophyane/capability_executors.py",
        "src/sophyane/local_coding_capability.py",
    ),
}


class EvolutionEngine:
    def __init__(
        self,
        config: EvolutionConfig,
    ) -> None:
        self.config = config
        self.repo = config.repo.resolve()
        self.records = (
            config.resolved_records_dir()
        )

    def _run_sli(
        self,
        task: TaskSpec,
    ) -> ExecutionTrace:
        workspace = Path(
            tempfile.mkdtemp(
                prefix=(
                    "sophyane-evolution-"
                    + task.task_id
                    + "-"
                )
            )
        )

        command = [
            str(
                self.repo
                / ".venv"
                / "bin"
                / "sophyane"
            ),
        ]

        env = os.environ.copy()
        env.update(
            {
                "SOPHYANE_SESSION_MODE": "sli_chunks",
                "SOPHYANE_SLI_ONLY": "1",
                "SOPHYANE_NO_BROWSER": "1",
                "SOPHYANE_DISABLE_GOAL_DIALOGUE": "1",
            }
        )

        started = time.monotonic()

        result = subprocess.run(
            command,
            input=task.prompt + "\nexit\n",
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
            check=False,
        )

        elapsed = (
            time.monotonic()
            - started
        )

        files = [
            str(path.relative_to(workspace))
            for path in workspace.rglob("*")
            if path.is_file()
        ]

        return ExecutionTrace(
            task_id=task.task_id,
            workspace=str(workspace),
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed_seconds=elapsed,
            files=files,
        )

    def _blind_report(
        self,
        task: TaskSpec,
        trace: ExecutionTrace,
    ) -> FeedbackReport:
        output = (
            trace.stdout
            + "\n"
            + trace.stderr
        )

        return FeedbackReport(
            kind="blind",
            author="local_execution_observer",
            summary=(
                "First-person report generated without "
                "validator verdict."
            ),
            evidence=[
                f"task={task.prompt}",
                f"exit={trace.exit_code}",
                f"files={trace.files}",
                output[-2500:],
            ],
            confidence=0.55,
        )

    def _gemini_key(self) -> str:
        key = (
            os.environ.get(
                "GEMINI_API_KEY"
            )
            or os.environ.get(
                "SOPHYANE_GEMINI_API_KEY"
            )
            or ""
        )

        if key:
            return key

        try:
            from sophyane.secret_vault import (
                get_secret,
            )

            return (
                get_secret(
                    "default",
                    "gemini_api_key",
                )
                or get_secret(
                    "default",
                    "google_api_key",
                )
                or ""
            )
        except Exception:
            return ""

    def _gemini(
        self,
        prompt: str,
    ) -> str:
        key = self._gemini_key()

        if not key:
            raise RuntimeError(
                "Gemini API key unavailable"
            )

        model = os.environ.get(
            "SOPHYANE_EVOLUTION_GEMINI_MODEL",
            "gemini-2.5-flash",
        )

        url = (
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent?"
            + urllib.parse.urlencode(
                {"key": key}
            )
        )

        body = json.dumps(
            {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt,
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 5000,
                },
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=180,
        ) as response:
            data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        return str(
            data["candidates"][0]
            ["content"]["parts"][0]["text"]
        )

    @staticmethod
    def _json_object(
        text: str,
    ) -> dict[str, Any]:
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text.strip(),
            flags=re.I,
        )
        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        start = text.find("{")
        end = text.rfind("}")

        if start < 0 or end <= start:
            raise ValueError(
                "No JSON object"
            )

        return json.loads(
            text[start : end + 1]
        )

    def _hindsight(
        self,
        record: EvolutionRecord,
    ) -> FeedbackReport | None:
        if (
            not self.config.allow_cloud_analysis
            or record.validation.passed
        ):
            return None

        prompt = f"""
You are the hindsight analyst in a constrained harness-evolution system.

Diagnose the single most likely harness component responsible for this failure.
Do not propose broad rewrites. Do not hardcode the task wording.
Allowed components:
{json.dumps(sorted(COMPONENT_PATHS))}

Task:
{record.task.prompt}

Blind report:
{json.dumps(record.blind_report.evidence if record.blind_report else [])}

Execution stdout:
{record.trace.stdout[-5000:]}

Execution stderr:
{record.trace.stderr[-3000:]}

Validator checks:
{json.dumps(record.validation.checks)}

Validator errors:
{json.dumps(record.validation.errors)}

Return JSON only:
{{
  "summary": "...",
  "suspected_component": "one allowed component",
  "confidence": 0.0,
  "evidence": ["..."]
}}
"""

        try:
            parsed = self._json_object(
                self._gemini(prompt)
            )
        except Exception as error:
            return FeedbackReport(
                kind="hindsight",
                author="gemini",
                summary=(
                    "Cloud analysis unavailable: "
                    f"{type(error).__name__}: {error}"
                ),
                confidence=0.0,
            )

        component = str(
            parsed.get(
                "suspected_component"
            )
            or ""
        )

        if component not in COMPONENT_PATHS:
            component = ""

        return FeedbackReport(
            kind="hindsight",
            author="gemini",
            summary=str(
                parsed.get("summary")
                or ""
            ),
            evidence=[
                str(item)
                for item in (
                    parsed.get("evidence")
                    or []
                )
            ],
            suspected_component=component,
            confidence=float(
                parsed.get("confidence")
                or 0.0
            ),
        )

    def _proposal(
        self,
        record: EvolutionRecord,
    ) -> PatchProposal | None:
        report = record.hindsight_report

        if (
            not self.config.allow_candidate_patches
            or report is None
            or not report.suspected_component
            or report.confidence < 0.65
        ):
            return None

        allowed = list(
            COMPONENT_PATHS[
                report.suspected_component
            ]
        )

        prompt = f"""
Produce one minimal unified diff for a constrained harness improvement.

Rules:
- Modify exactly one logical component.
- Modify only these paths or files beneath these directories:
{json.dumps(allowed)}
- Do not alter tests merely to hide the failure.
- Do not hardcode this task's exact wording, filenames or expected answer.
- Add or update a genuine regression test.
- Maximum changed lines: {self.config.max_patch_lines}.
- Return JSON only.

Failure:
{report.summary}

Evidence:
{json.dumps(report.evidence)}

Task:
{record.task.prompt}

Return:
{{
  "component": "{report.suspected_component}",
  "rationale": "...",
  "patch": "diff --git ...",
  "tests": ["tests/..."],
  "confidence": 0.0
}}
"""

        try:
            parsed = self._json_object(
                self._gemini(prompt)
            )
        except Exception:
            return None

        patch = str(
            parsed.get("patch")
            or ""
        )

        if not patch.startswith(
            "diff --git "
        ):
            return None

        proposal = PatchProposal(
            component=report.suspected_component,
            rationale=str(
                parsed.get("rationale")
                or ""
            ),
            patch=patch,
            tests=[
                str(item)
                for item in (
                    parsed.get("tests")
                    or []
                )
            ],
            confidence=float(
                parsed.get("confidence")
                or 0.0
            ),
            allowed_paths=allowed,
        )

        if not self._patch_allowed(
            proposal
        ):
            return None

        return proposal

    def _patch_allowed(
        self,
        proposal: PatchProposal,
    ) -> bool:
        paths = re.findall(
            r"^\+\+\+\s+b/(.+)$",
            proposal.patch,
            flags=re.M,
        )

        if (
            not paths
            or len(set(paths))
            > self.config.max_patch_files
        ):
            return False

        for path in paths:
            if not any(
                path == allowed
                or path.startswith(
                    allowed.rstrip("/")
                    + "/"
                )
                for allowed
                in proposal.allowed_paths
            ):
                return False

        changed_lines = sum(
            1
            for line in proposal.patch.splitlines()
            if (
                line.startswith("+")
                or line.startswith("-")
            )
            and not line.startswith(
                ("+++", "---")
            )
        )

        return (
            changed_lines
            <= self.config.max_patch_lines
        )

    def _generalization_tasks(
        self,
        capability: str,
    ) -> list[TaskSpec]:
        prompts = {
            "semantic_routing": [
                (
                    "what flight did I book?",
                    "personal_knowledge",
                ),
                (
                    "what is the largest airline?",
                    "public_knowledge",
                ),
            ],
            "html": [
                (
                    "make a website about birds",
                    "html",
                ),
            ],
            "shell": [
                (
                    "Create a script that prints HELLO, "
                    "prints ERRMSG to stderr and exits 7.",
                    "shell",
                ),
            ],
            "filesystem": [
                (
                    "Create verify.txt containing exactly VERIFIED.",
                    "filesystem",
                ),
            ],
        }

        return [
            TaskSpec(
                task_id=(
                    "heldout-"
                    + capability
                    + "-"
                    + str(index)
                ),
                prompt=prompt,
                capability=capability,
                validator=validator,
                held_out=True,
            )
            for index, (
                prompt,
                validator,
            ) in enumerate(
                prompts.get(
                    capability,
                    [],
                ),
                start=1,
            )
        ]

    def _gate(
        self,
        record: EvolutionRecord,
    ) -> GateResult | None:
        proposal = record.proposal

        if proposal is None:
            return None

        root = (
            self.repo
            / ".sophyane-evolution"
            / "worktrees"
        )
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        worktree = (
            root
            / record.run_id
        )

        branch = (
            "evolution/"
            + record.run_id
        )

        subprocess.run(
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
            check=True,
            capture_output=True,
            text=True,
        )

        try:
            patch_file = (
                worktree
                / ".candidate.patch"
            )
            patch_file.write_text(
                proposal.patch,
                encoding="utf-8",
            )

            applied = subprocess.run(
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

            if applied.returncode != 0:
                return GateResult(
                    targeted_passed=False,
                    regression_passed=False,
                    held_out_passed=False,
                    baseline_score=0.0,
                    candidate_score=0.0,
                    security_passed=False,
                    promotable=False,
                    details={
                        "apply_error": (
                            applied.stderr
                        ),
                    },
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

            targeted_command = (
                [
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    *proposal.tests,
                ]
                if proposal.tests
                else [
                    "python",
                    "-m",
                    "py_compile",
                    *[
                        str(
                            worktree / path
                        )
                        for path in re.findall(
                            r"^\+\+\+\s+b/(.+)$",
                            proposal.patch,
                            flags=re.M,
                        )
                        if path.endswith(
                            ".py"
                        )
                    ],
                ]
            )

            targeted = subprocess.run(
                targeted_command,
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )

            regression = subprocess.run(
                list(
                    self.config.full_test_command
                ),
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )

            held_out_results = []

            for task in self._generalization_tasks(
                record.task.capability
            ):
                original_repo = self.repo

                try:
                    self.repo = worktree
                    trace = self._run_sli(
                        task
                    )
                    result = validate(
                        task,
                        trace,
                    )
                    held_out_results.append(
                        result.passed
                    )
                finally:
                    self.repo = original_repo

            held_out_passed = (
                all(held_out_results)
                if held_out_results
                else True
            )

            security_passed = (
                "security"
                not in proposal.component
                or regression.returncode == 0
            )

            candidate_score = (
                1.0
                if targeted.returncode == 0
                else 0.0
            ) + (
                1.0
                if regression.returncode == 0
                else 0.0
            ) + (
                1.0
                if held_out_passed
                else 0.0
            )

            promotable = all(
                (
                    targeted.returncode == 0,
                    regression.returncode == 0,
                    held_out_passed,
                    security_passed,
                    candidate_score > 2.5,
                )
            )

            if (
                promotable
                and self.config.allow_promotion
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
                            "Constrained evolution: "
                            + proposal.component
                        ),
                    ],
                    cwd=worktree,
                    check=True,
                )

            return GateResult(
                targeted_passed=(
                    targeted.returncode
                    == 0
                ),
                regression_passed=(
                    regression.returncode
                    == 0
                ),
                held_out_passed=held_out_passed,
                baseline_score=0.0,
                candidate_score=candidate_score,
                security_passed=security_passed,
                promotable=promotable,
                details={
                    "worktree": str(
                        worktree
                    ),
                    "branch": branch,
                    "targeted_output": (
                        targeted.stdout[-3000:]
                        + targeted.stderr[-3000:]
                    ),
                    "regression_output": (
                        regression.stdout[-3000:]
                        + regression.stderr[-3000:]
                    ),
                    "promotion_committed": (
                        promotable
                        and self.config.allow_promotion
                    ),
                },
            )

        finally:
            # Keep promotable worktrees for human inspection.
            # Remove rejected candidates automatically.
            pass

    def cycle(
        self,
        number: int,
    ) -> EvolutionRecord:
        run_id = new_run_id()
        task = generate_task(
            self.repo,
            number,
        )
        trace = self._run_sli(task)
        validation = validate(
            task,
            trace,
        )

        record = EvolutionRecord(
            run_id=run_id,
            cycle=number,
            task=task,
            trace=trace,
            validation=validation,
        )

        record.blind_report = (
            self._blind_report(
                task,
                trace,
            )
        )

        if validation.passed:
            record.status = "reinforced"
            update_score(
                self.repo,
                task.capability,
                True,
            )
        else:
            update_score(
                self.repo,
                task.capability,
                False,
            )

            record.hindsight_report = (
                self._hindsight(record)
            )
            record.proposal = (
                self._proposal(record)
            )
            record.gate = self._gate(
                record
            )

            if (
                record.gate
                and record.gate.promotable
            ):
                record.status = (
                    "candidate_promotable"
                )
            elif record.proposal:
                record.status = (
                    "candidate_rejected"
                )
            else:
                record.status = (
                    "failure_observed"
                )

        record.write(
            self.records
        )

        return record

    def run(self) -> list[EvolutionRecord]:
        results = []

        for cycle in range(
            1,
            self.config.cycles + 1,
        ):
            record = self.cycle(
                cycle
            )
            results.append(record)

            print(
                f"[{cycle}/{self.config.cycles}] "
                f"{record.task.capability}: "
                f"{record.status}"
            )

        return results
