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
import random
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .curriculum import (
    focused_capability,
    generate_focused_task,
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
from .principles import PrincipleStore
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
        self.principles = PrincipleStore(
            self.repo
        )
        self._focus_capability = ""
        self._focus_remaining = 0

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

    def _local_llm(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 1200,
    ) -> str:
        """Use only the configured local llama.cpp endpoint."""
        body = json.dumps(
            {
                "model": "local",
                "messages": [
                    {
                        "role": "system",
                        "content": system,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            "http://127.0.0.1:8766/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=120,
        ) as response:
            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        return str(
            payload["choices"][0]
            ["message"]["content"]
        )

    def _blind_report(
        self,
        task: TaskSpec,
        trace: ExecutionTrace,
    ) -> FeedbackReport:
        """First-person report created before revealing validator results."""
        execution_excerpt = (
            trace.stdout
            + "\n"
            + trace.stderr
        )[-5000:]

        prompt = f"""
You are the agent that just attempted a harness task.

You may inspect only:
- the task;
- the execution trace;
- files created.

You must not see or infer the validator verdict.

Report in first person:
1. the plan you believe you followed;
2. what you believe succeeded;
3. where you felt friction or uncertainty;
4. the single harness component most likely to need improvement;
5. one reusable principle, not a task-specific fix.

Return JSON only:
{{
  "summary": "...",
  "suspected_component": "...",
  "confidence": 0.0,
  "evidence": ["..."],
  "general_principle": "..."
}}

Task:
{task.prompt}

Capability:
{task.capability}

Exit code:
{trace.exit_code}

Files:
{json.dumps(trace.files)}

Trace:
{execution_excerpt}
"""

        try:
            parsed = self._json_object(
                self._local_llm(
                    system=(
                        "Produce a blind first-person execution report. "
                        "Do not claim to know validator results."
                    ),
                    prompt=prompt,
                )
            )

            return FeedbackReport(
                kind="blind",
                author="local_gguf",
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
                ][:8],
                suspected_component=str(
                    parsed.get(
                        "suspected_component"
                    )
                    or ""
                ),
                confidence=float(
                    parsed.get("confidence")
                    or 0.0
                ),
                general_principle=str(
                    parsed.get(
                        "general_principle"
                    )
                    or ""
                ),
            )

        except Exception as error:
            return FeedbackReport(
                kind="blind",
                author="deterministic_observer",
                summary=(
                    "Local blind report unavailable; "
                    "recorded deterministic first-person evidence."
                ),
                evidence=[
                    f"task={task.prompt}",
                    f"exit={trace.exit_code}",
                    f"files={trace.files}",
                    execution_excerpt,
                    (
                        "local_report_error="
                        f"{type(error).__name__}: {error}"
                    ),
                ],
                confidence=0.40,
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

    def _evolution_local_llm(
        self,
        prompt: str,
        *,
        max_tokens: int = 16384,
    ) -> str:
        """Use the dedicated larger local evolution analyst."""
        endpoint = os.environ.get(
            "SOPHYANE_EVOLUTION_LOCAL_ENDPOINT",
            "http://127.0.0.1:8767",
        ).rstrip("/")

        model = os.environ.get(
            "SOPHYANE_EVOLUTION_LOCAL_MODEL_NAME",
            "local-evolution",
        )

        # Candidate prompts may contain large source excerpts. Keep the local
        # request within the dedicated server's context window while preserving
        # both the governing constraints at the beginning and source context at
        # the end.
        raw_prompt = str(prompt or "")

        prompt_character_limit = max(
            4000,
            int(
                os.environ.get(
                    "SOPHYANE_EVOLUTION_LOCAL_MAX_PROMPT_CHARS",
                    "18000",
                )
            ),
        )

        if len(raw_prompt) > prompt_character_limit:
            head_size = int(
                prompt_character_limit * 0.40
            )
            tail_size = (
                prompt_character_limit
                - head_size
            )

            prompt = (
                raw_prompt[:head_size]
                + "\n\n"
                + "[LOCAL ANALYST PROMPT COMPACTED: "
                + str(
                    len(raw_prompt)
                    - prompt_character_limit
                )
                + " CHARACTERS OMITTED]"
                + "\n\n"
                + raw_prompt[-tail_size:]
            )
        else:
            prompt = raw_prompt

        local_output_limit = max(
            256,
            int(
                os.environ.get(
                    "SOPHYANE_EVOLUTION_LOCAL_MAX_OUTPUT_TOKENS",
                    "2048",
                )
            ),
        )

        effective_max_tokens = min(
            max(64, int(max_tokens)),
            local_output_limit,
        )

        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are Sophyane's constrained harness "
                            "evolution analyst. Return exactly the "
                            "requested JSON or unified Git diff. "
                            "Never weaken validators, security boundaries, "
                            "private-data boundaries, or promotion gates."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0.05,
                "max_tokens": effective_max_tokens,
            }
        ).encode("utf-8")

        if len(raw_prompt) != len(prompt):
            print(
                "Local evolution prompt compacted: "
                f"{len(raw_prompt)} → {len(prompt)} characters"
            )

        print(
            "Local evolution generation budget: "
            f"{effective_max_tokens} tokens"
        )

        request = urllib.request.Request(
            endpoint + "/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        timeout = int(
            os.environ.get(
                "SOPHYANE_EVOLUTION_LOCAL_TIMEOUT_SECONDS",
                "900",
            )
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                payload = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

        except urllib.error.HTTPError as error:
            try:
                error_body = (
                    error.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )
            except Exception:
                error_body = ""

            raise RuntimeError(
                "Larger local evolution analyst rejected the request. "
                f"status={error.code}; "
                f"prompt_characters={len(prompt)}; "
                f"max_output_tokens={effective_max_tokens}; "
                f"body={error_body[:3000]}"
            ) from error

        except Exception as error:
            raise RuntimeError(
                "Larger local evolution analyst failed: "
                f"{type(error).__name__}: {error}"
            ) from error

        choices = payload.get("choices") or []

        if not choices:
            raise RuntimeError(
                "Larger local evolution analyst returned no choices"
            )

        output = str(
            choices[0]
            .get("message", {})
            .get("content")
            or ""
        )

        if not output.strip():
            raise RuntimeError(
                "Larger local evolution analyst returned empty output"
            )

        return output

    @staticmethod
    def _cloud_failure_allows_local_fallback(
        error: Exception,
    ) -> bool:
        """Classify cloud failures that permit the local analyst."""
        message = (
            f"{type(error).__name__}: {error}"
        ).casefold()

        markers = (
            "gemini api key unavailable",
            "daily quota",
            "quota exceeded",
            "resource_exhausted",
            "free_tier_requests",
            "http error 429",
            "http error 500",
            "http error 502",
            "http error 503",
            "http error 504",
            "status=429",
            "status=500",
            "status=502",
            "status=503",
            "status=504",
            "service unavailable",
            "network request failed",
            "timed out",
            "timeout",
        )

        return any(
            marker in message
            for marker in markers
        )

    def _analyst_llm(
        self,
        prompt: str,
        *,
        max_tokens: int = 16384,
        cloud_first: bool = True,
    ) -> str:
        """Use Gemini first, then the dedicated larger local analyst."""
        local_enabled = (
            os.environ.get(
                "SOPHYANE_EVOLUTION_ALLOW_LOCAL_FALLBACK",
                "1",
            )
            != "0"
        )

        force_local = (
            os.environ.get(
                "SOPHYANE_EVOLUTION_FORCE_LOCAL_ANALYST",
                "0",
            )
            == "1"
        )

        if force_local or not cloud_first:
            print(
                "Evolution analyst route: larger local GGUF"
            )
            return self._evolution_local_llm(
                prompt,
                max_tokens=max_tokens,
            )

        try:
            output = self._gemini(prompt)
            print(
                "Evolution analyst route: Gemini"
            )
            return output

        except Exception as cloud_error:
            if (
                not local_enabled
                or not self._cloud_failure_allows_local_fallback(
                    cloud_error
                )
            ):
                raise

            print(
                "Gemini unavailable; using larger local "
                "evolution analyst."
            )
            print(
                "Cloud failure: "
                f"{type(cloud_error).__name__}: "
                f"{cloud_error}"
            )

            try:
                return self._evolution_local_llm(
                    prompt,
                    max_tokens=max_tokens,
                )
            except Exception as local_error:
                raise RuntimeError(
                    "Both evolution analysts failed. "
                    f"Cloud: {type(cloud_error).__name__}: "
                    f"{cloud_error}. "
                    f"Local: {type(local_error).__name__}: "
                    f"{local_error}"
                ) from local_error

    def _gemini(
        self,
        prompt: str,
    ) -> str:
        """Generate complete Gemini output with explicit completion checks."""
        key = self._gemini_key()

        if not key:
            raise RuntimeError(
                "Gemini API key unavailable"
            )

        model = os.environ.get(
            "SOPHYANE_EVOLUTION_GEMINI_MODEL",
            "gemini-2.5-flash",
        )

        max_output_tokens = int(
            os.environ.get(
                "SOPHYANE_EVOLUTION_GEMINI_MAX_OUTPUT_TOKENS",
                "16384",
            )
        )

        thinking_budget = int(
            os.environ.get(
                "SOPHYANE_EVOLUTION_GEMINI_THINKING_BUDGET",
                "0",
            )
        )

        url = (
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent?"
            + urllib.parse.urlencode(
                {"key": key}
            )
        )

        generation_config = {
            "temperature": 0.1,
            "maxOutputTokens": max_output_tokens,
        }

        # Gemini 2.5 Flash supports disabling or bounding thinking.
        if model.startswith("gemini-2.5"):
            generation_config[
                "thinkingConfig"
            ] = {
                "thinkingBudget": (
                    thinking_budget
                )
            }

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
                "generationConfig": (
                    generation_config
                ),
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

        max_attempts = max(
            1,
            int(
                os.environ.get(
                    "SOPHYANE_EVOLUTION_GEMINI_MAX_ATTEMPTS",
                    "4",
                )
            ),
        )

        base_delay = max(
            0.1,
            float(
                os.environ.get(
                    "SOPHYANE_EVOLUTION_GEMINI_RETRY_BASE_SECONDS",
                    "2",
                )
            ),
        )

        retryable_statuses = {
            408,
            429,
            500,
            502,
            503,
            504,
        }

        data = None
        last_error: Exception | None = None

        for attempt in range(
            1,
            max_attempts + 1,
        ):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=240,
                ) as response:
                    data = json.loads(
                        response.read().decode(
                            "utf-8"
                        )
                    )

                break

            except urllib.error.HTTPError as error:
                last_error = error
                status = int(
                    getattr(
                        error,
                        "code",
                        0,
                    )
                    or 0
                )

                try:
                    response_body = (
                        error.read()
                        .decode(
                            "utf-8",
                            errors="replace",
                        )
                    )
                except Exception:
                    response_body = ""

                if (
                    status not in retryable_statuses
                    or attempt >= max_attempts
                ):
                    raise RuntimeError(
                        "Gemini HTTP request failed. "
                        f"status={status}; "
                        f"attempt={attempt}/{max_attempts}; "
                        f"body={response_body[:2000]}"
                    ) from error

                retry_after = 0.0

                try:
                    retry_after = float(
                        error.headers.get(
                            "Retry-After",
                            "0",
                        )
                        or 0
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    retry_after = 0.0

                exponential = (
                    base_delay
                    * (
                        2
                        ** (
                            attempt - 1
                        )
                    )
                )

                jitter = random.uniform(
                    0.0,
                    min(
                        2.0,
                        exponential * 0.25,
                    ),
                )

                delay = max(
                    retry_after,
                    exponential + jitter,
                )

                print(
                    "Gemini transient HTTP failure: "
                    f"{status}; "
                    f"retrying in {delay:.1f}s "
                    f"({attempt}/{max_attempts})"
                )

                time.sleep(delay)

            except (
                urllib.error.URLError,
                TimeoutError,
            ) as error:
                last_error = error

                if attempt >= max_attempts:
                    raise RuntimeError(
                        "Gemini network request failed "
                        f"after {max_attempts} attempts: "
                        f"{type(error).__name__}: {error}"
                    ) from error

                exponential = (
                    base_delay
                    * (
                        2
                        ** (
                            attempt - 1
                        )
                    )
                )

                jitter = random.uniform(
                    0.0,
                    min(
                        2.0,
                        exponential * 0.25,
                    ),
                )

                delay = (
                    exponential
                    + jitter
                )

                print(
                    "Gemini transient network failure: "
                    f"{type(error).__name__}; "
                    f"retrying in {delay:.1f}s "
                    f"({attempt}/{max_attempts})"
                )

                time.sleep(delay)

        if data is None:
            raise RuntimeError(
                "Gemini produced no response after "
                f"{max_attempts} attempts: {last_error}"
            )

        candidates = data.get(
            "candidates"
        ) or []

        if not candidates:
            feedback = data.get(
                "promptFeedback"
            ) or {}

            raise RuntimeError(
                "Gemini returned no candidates. "
                f"Prompt feedback: {feedback}"
            )

        candidate = candidates[0]
        finish_reason = str(
            candidate.get(
                "finishReason"
            )
            or ""
        )

        parts = (
            candidate.get(
                "content",
                {},
            ).get(
                "parts",
                []
            )
            or []
        )

        output = "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict)
        )

        usage = data.get(
            "usageMetadata"
        ) or {}

        if finish_reason == "MAX_TOKENS":
            raise RuntimeError(
                "Gemini output was truncated at MAX_TOKENS. "
                f"characters={len(output)}; "
                f"usage={usage}; "
                f"configured_max={max_output_tokens}; "
                f"thinking_budget={thinking_budget}"
            )

        allowed_finish_reasons = {
            "",
            "STOP",
            "FINISH_REASON_UNSPECIFIED",
        }

        if (
            finish_reason
            not in allowed_finish_reasons
        ):
            raise RuntimeError(
                "Gemini generation stopped abnormally. "
                f"finish_reason={finish_reason}; "
                f"finish_message="
                f"{candidate.get('finishMessage')}; "
                f"usage={usage}"
            )

        if not output.strip():
            raise RuntimeError(
                "Gemini returned an empty text response. "
                f"finish_reason={finish_reason}; "
                f"usage={usage}"
            )

        return output

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

Compare the blind report with the objective validator result.

Identify:
- what the acting system believed;
- what the validator proved;
- the specific mismatch;
- one task-agnostic reusable design principle.

Return JSON only:
{{
  "summary": "...",
  "suspected_component": "one allowed component",
  "confidence": 0.0,
  "evidence": ["..."],
  "mismatch": "...",
  "general_principle": "..."
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
            mismatch=str(
                parsed.get("mismatch")
                or ""
            ),
            general_principle=str(
                parsed.get(
                    "general_principle"
                )
                or ""
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
            or not report.general_principle
            or not self.principles.patch_eligible(
                component=report.suspected_component,
                principle=report.general_principle,
            )
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

Blind-versus-verdict mismatch:
{report.mismatch}

Recurrent general principle:
{report.general_principle}

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

    def _score_generalization_tasks(
        self,
        *,
        repo: Path,
        tasks: list[TaskSpec],
    ) -> tuple[float, list[dict[str, Any]]]:
        if not tasks:
            return 1.0, []

        previous_repo = self.repo
        results: list[dict[str, Any]] = []

        try:
            self.repo = repo

            for task in tasks:
                trace = self._run_sli(task)
                result = validate(
                    task,
                    trace,
                )

                results.append(
                    {
                        "task_id": task.task_id,
                        "passed": result.passed,
                        "checks": result.checks,
                        "errors": result.errors,
                    }
                )

        finally:
            self.repo = previous_repo

        passes = sum(
            1
            for item in results
            if item["passed"]
        )

        return (
            passes / max(1, len(results)),
            results,
        )

    def _gate(
        self,
        record: EvolutionRecord,
    ) -> GateResult | None:
        proposal = record.proposal

        if proposal is None:
            return None

        generalization_tasks = (
            self._generalization_tasks(
                record.task.capability
            )
        )

        (
            baseline_score,
            baseline_details,
        ) = self._score_generalization_tasks(
            repo=self.repo,
            tasks=generalization_tasks,
        )

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

            (
                candidate_generalization_score,
                candidate_generalization_details,
            ) = self._score_generalization_tasks(
                repo=worktree,
                tasks=generalization_tasks,
            )

            held_out_passed = (
                candidate_generalization_score
                >= baseline_score
                and candidate_generalization_score
                >= 0.75
            )

            security_passed = (
                "security"
                not in proposal.component
                or regression.returncode == 0
            )

            candidate_score = (
                (
                    1.0
                    if targeted.returncode == 0
                    else 0.0
                )
                + (
                    1.0
                    if regression.returncode == 0
                    else 0.0
                )
                + candidate_generalization_score
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
                baseline_score=baseline_score,
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
                    "baseline_generalization": (
                        baseline_details
                    ),
                    "candidate_generalization": (
                        candidate_generalization_details
                    ),
                    "baseline_generalization_score": (
                        baseline_score
                    ),
                    "candidate_generalization_score": (
                        candidate_generalization_score
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

        if (
            not self._focus_capability
            or self._focus_remaining <= 0
        ):
            self._focus_capability = (
                focused_capability(
                    self.repo,
                    threshold=(
                        self.config.mastery_threshold
                    ),
                    minimum_samples=(
                        self.config.minimum_mastery_samples
                    ),
                )
            )
            self._focus_remaining = max(
                1,
                self.config.focus_window,
            )

        task = generate_focused_task(
            self.repo,
            number,
            self._focus_capability,
        )
        self._focus_remaining -= 1
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

            self.principles.record_success(
                capability=task.capability,
                task_id=task.task_id,
                checks=validation.checks,
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

            if (
                record.hindsight_report
                and record.hindsight_report.general_principle
                and record.hindsight_report.suspected_component
            ):
                learned = (
                    self.principles.record_failure_principle(
                        component=(
                            record.hindsight_report
                            .suspected_component
                        ),
                        capability=task.capability,
                        principle=(
                            record.hindsight_report
                            .general_principle
                        ),
                        task_id=task.task_id,
                        confidence=(
                            record.hindsight_report
                            .confidence
                        ),
                        evidence=(
                            record.hindsight_report
                            .evidence
                            + [
                                record.hindsight_report
                                .mismatch
                            ]
                        ),
                    )
                )

                if learned:
                    record.hindsight_report.evidence.append(
                        "principle_status="
                        + str(
                            learned.get("status")
                            or "candidate"
                        )
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
