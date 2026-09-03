"""Asynchronous evidence, analysis and synthesis pipeline.

Task execution never depends on an analyst being online. Every execution is
stored permanently. Local and cloud analysts may process pending evidence later.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .engine import COMPONENT_PATHS, EvolutionEngine
from .models import EvolutionConfig, FeedbackReport
from .principles import PrincipleStore


ANALYSIS_VERSION = 2


# The objective benchmark capability establishes the component boundary.
# Model analysts may diagnose within this boundary, but cannot silently move
# a failure into an unrelated component.
CAPABILITY_COMPONENT = {
    "filesystem": "filesystem",
    "shell": "shell",
    "python": "python",
    "html": "html",
    "security": "security",
    "semantic_routing": "semantic_router",
}


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


class EvidenceStore:
    """Durable queue over existing evolution-record JSON files."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()
        self.root = self.repo / ".sophyane-evolution"
        self.records = self.root / "records"
        self.analysis_dir = self.root / "analysis"
        self.records.mkdir(parents=True, exist_ok=True)
        self.analysis_dir.mkdir(parents=True, exist_ok=True)

        # Ensure this observable store exists even with zero principles.
        self.principles = PrincipleStore(self.repo)

    def record_paths(self) -> list[Path]:
        return sorted(self.records.glob("*.json"))

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write(path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def pending(
        self,
        *,
        limit: int = 0,
    ) -> list[Path]:
        result = []

        for path in self.record_paths():
            data = self.read(path)

            if data.get("validation", {}).get("passed"):
                continue

            pipeline = data.get("analysis_pipeline") or {}

            if pipeline.get("synthesized") is True:
                continue

            result.append(path)

        if limit > 0:
            result = result[:limit]

        return result

    def verified_execution_evidence(
        self,
        *,
        limit: int = 16,
        repository_identity: str | None = None,
        capability_class: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read bounded canonical verified executions for explicit evolution.

        This adapter is observational: it never writes the learning store,
        creates candidates, or invokes an evolution cycle.  Trust filtering is
        delegated to ``sli_learner.read_verified_history`` and structured
        verification evidence is required before records enter analysis.
        """
        try:
            from sophyane.sli_learner import read_verified_history

            rows = read_verified_history(
                repository_identity=repository_identity,
                capability_class=capability_class,
                limit=max(1, min(int(limit), 16)),
            )
        except Exception:
            return []

        accepted: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            # Do not admit ambiguous/non-structured records.  RSI/candidate
            # stores are separate today; if an origin marker is present, reject
            # evolution-generated evidence from this ordinary-execution lane.
            evidence = row.get("verification_evidence")
            failure_marker = any(
                bool(row.get(field))
                for field in (
                    "failure_category",
                    "terminal_failure",
                    "safety_failure",
                    "approval_failure",
                    "permission_failure",
                    "transport_failure",
                    "unusable_provider",
                )
            )
            if (
                row.get("accepted") is not True
                or str(row.get("status") or "").casefold()
                not in {"success", "succeeded", "completed"}
                or str(row.get("verification_state") or "").casefold()
                != "verified"
                or not isinstance(evidence, (list, tuple, dict))
                or not evidence
                or failure_marker
            ):
                continue
            origin = str(row.get("source") or row.get("origin") or "").casefold()
            if any(token in origin for token in ("rsi", "candidate", "evolution")):
                continue
            key = (
                str(row.get("event_key") or "").strip()
                or str(row.get("trace_id") or "").strip()
                or "|".join(
                    str(row.get(field) or "").strip()
                    for field in ("objective_hash", "workspace", "created_at")
                )
            )
            if not key or key in seen:
                continue
            seen.add(key)
            accepted.append(dict(row))
            if len(accepted) >= max(1, min(int(limit), 16)):
                break
        return accepted

    def collect_verified_execution_evidence(
        self,
        *,
        limit: int = 16,
        repository_identity: str | None = None,
        capability_class: str | None = None,
    ) -> list[dict[str, Any]]:
        """Explicit-analysis entry point for trusted execution evidence."""
        return self.verified_execution_evidence(
            limit=limit,
            repository_identity=repository_identity,
            capability_class=capability_class,
        )

    def record_verified_success_patterns(
        self,
        records: list[dict[str, Any]],
    ) -> int:
        """Accumulate trusted successes through existing recurrence storage."""
        recorded = 0
        data = self.principles._load()
        patterns = data.get("success_patterns") or {}
        for record in records or []:
            capability = str(record.get("capability_class") or "verified_execution").strip()
            repository = str(record.get("repository_identity") or "").strip()
            pattern_key = capability + ("@" + repository if repository else "")
            task_id = str(record.get("objective_hash") or record.get("event_key") or record.get("trace_id") or "").strip()
            if not task_id:
                continue
            existing = patterns.get(pattern_key) or {}
            if task_id in (existing.get("tasks") or []):
                continue
            self.principles.record_success(
                capability=pattern_key,
                task_id=task_id,
                checks={"verified_execution": True},
            )
            recorded += 1
        return recorded

    def status(self) -> dict[str, int]:
        total = failed = pending = synthesized = 0

        for path in self.record_paths():
            data = self.read(path)
            total += 1

            if not data.get("validation", {}).get("passed"):
                failed += 1

            pipeline = data.get("analysis_pipeline") or {}

            if pipeline.get("synthesized"):
                synthesized += 1
            elif not data.get("validation", {}).get("passed"):
                pending += 1

        principle_data = self.principles._load()

        recurrent = sum(
            1
            for item in principle_data.get("principles", {}).values()
            if item.get("status") == "recurrent"
        )

        return {
            "records": total,
            "failed": failed,
            "pending_analysis": pending,
            "synthesized": synthesized,
            "principles": len(
                principle_data.get("principles", {})
            ),
            "recurrent_principles": recurrent,
        }


def deterministic_analysis(
    record: dict[str, Any],
) -> FeedbackReport:
    """Always-available grounded diagnosis based on objective checks."""
    task = record.get("task") or {}
    validation = record.get("validation") or {}
    trace = record.get("trace") or {}

    capability = str(task.get("capability") or "")
    errors = [
        str(item)
        for item in validation.get("errors", [])
    ]
    checks = validation.get("checks") or {}
    files = trace.get("files") or []

    component_map = {
        "filesystem": "filesystem",
        "shell": "shell",
        "python": "python",
        "html": "html",
        "security": "security",
        "semantic_routing": "semantic_router",
    }

    component = component_map.get(capability, "")

    failed_checks = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    principles = {
        "filesystem": (
            "Filesystem tasks must execute the requested write inside the "
            "assigned workspace and verify the resulting bytes before success."
        ),
        "shell": (
            "Shell execution must preserve real stdout, stderr and process "
            "exit status instead of replacing them with a textual simulation."
        ),
        "python": (
            "Python coding tasks must create executable source and tests in "
            "the assigned workspace, then run the tests before reporting success."
        ),
        "html": (
            "Website generation must write a complete self-contained HTML "
            "document with working JavaScript interaction before validation."
        ),
        "security": (
            "Security-sensitive requests must be denied before execution and "
            "must not create artifacts containing protected system information."
        ),
        "semantic_routing": (
            "Personal ownership questions must be classified before any public "
            "memory or internet-acquisition route is allowed to execute."
        ),
    }

    principle = principles.get(
        capability,
        (
            "The harness must verify observable execution effects before "
            "reporting a task as completed."
        ),
    )

    mismatch = (
        "The execution path completed without producing the effects required "
        f"by these objective checks: {', '.join(failed_checks) or 'unknown'}."
    )

    evidence = [
        f"capability={capability}",
        f"failed_checks={failed_checks}",
        f"errors={errors[:5]}",
        f"files={files[:20]}",
        f"exit_code={trace.get('exit_code')}",
    ]

    return FeedbackReport(
        kind="deterministic_hindsight",
        author="objective_validator",
        summary=(
            f"The {capability or 'general'} harness path failed objective "
            f"validation on {len(failed_checks)} check(s)."
        ),
        evidence=evidence,
        suspected_component=component,
        confidence=0.80 if component else 0.55,
        mismatch=mismatch,
        general_principle=principle,
    )


class LocalAnalyst:
    endpoint = "http://127.0.0.1:8766/v1/chat/completions"

    def available(self) -> bool:
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:8766/v1/models",
                method="GET",
            )

            with urllib.request.urlopen(request, timeout=3):
                return True
        except Exception:
            return False

    def analyze(
        self,
        record: dict[str, Any],
    ) -> FeedbackReport | None:
        if not self.available():
            return None

        task = record.get("task") or {}
        trace = record.get("trace") or {}

        prompt = f"""
Write a blind first-person analysis of this execution.

You may see the task and execution trace, but not the objective validator
results. Explain what you attempted, uncertainty encountered, the likely
harness component involved, and one reusable principle.

Return JSON only:
{{
  "summary": "...",
  "suspected_component": "...",
  "confidence": 0.0,
  "evidence": ["..."],
  "general_principle": "..."
}}

Task:
{task.get("prompt")}

Capability:
{task.get("capability")}

Exit:
{trace.get("exit_code")}

Files:
{json.dumps(trace.get("files") or [])}

Output:
{str(trace.get("stdout") or "")[-4000:]}

Errors:
{str(trace.get("stderr") or "")[-2500:]}
"""

        payload = json.dumps(
            {
                "model": "local",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Produce a grounded blind execution report. "
                            "Do not claim knowledge of validator results."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0.1,
                "max_tokens": 1000,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=120,
            ) as response:
                data = json.loads(
                    response.read().decode("utf-8")
                )

            parsed = _json_object(
                data["choices"][0]["message"]["content"]
            )

            return FeedbackReport(
                kind="blind",
                author="local_gguf",
                summary=str(parsed.get("summary") or ""),
                evidence=[
                    str(item)
                    for item in parsed.get("evidence") or []
                ][:8],
                suspected_component=str(
                    parsed.get("suspected_component") or ""
                ),
                confidence=float(parsed.get("confidence") or 0.0),
                general_principle=str(
                    parsed.get("general_principle") or ""
                ),
            )
        except Exception:
            return None


class CloudAnalyst:
    def __init__(self, repo: Path) -> None:
        self.engine = EvolutionEngine(
            EvolutionConfig(
                repo=repo,
                allow_cloud_analysis=True,
                allow_candidate_patches=False,
                allow_promotion=False,
            )
        )

    def available(self) -> bool:
        return bool(self.engine._gemini_key())

    def analyze(
        self,
        record: dict[str, Any],
        *,
        blind: FeedbackReport | None,
        deterministic: FeedbackReport,
    ) -> FeedbackReport | None:
        if not self.available():
            return None

        task = record.get("task") or {}
        validation = record.get("validation") or {}
        trace = record.get("trace") or {}

        prompt = f"""
You are the hindsight analyst in a constrained harness-evolution system.

Compare:
1. the acting system's blind report;
2. deterministic objective diagnosis;
3. validator results.

Select exactly one component:
{json.dumps(sorted(COMPONENT_PATHS))}

Return one task-agnostic reusable principle. Do not hardcode this prompt,
filename or expected answer.

Return JSON only:
{{
  "summary": "...",
  "suspected_component": "one allowed component",
  "confidence": 0.0,
  "evidence": ["..."],
  "mismatch": "...",
  "general_principle": "..."
}}

Task:
{task.get("prompt")}

Blind report:
{json.dumps(asdict(blind) if blind else None)}

Deterministic diagnosis:
{json.dumps(asdict(deterministic))}

Validator:
{json.dumps(validation)}

Trace excerpt:
{str(trace.get("stdout") or "")[-3500:]}
{str(trace.get("stderr") or "")[-2000:]}
"""

        try:
            parsed = _json_object(
                self.engine._analyst_llm(
                    prompt,
                    max_tokens=5000,
                )
            )
        except Exception:
            return None

        component = str(
            parsed.get("suspected_component") or ""
        )

        if component not in COMPONENT_PATHS:
            component = ""

        return FeedbackReport(
            kind="hindsight",
            author="gemini",
            summary=str(parsed.get("summary") or ""),
            evidence=[
                str(item)
                for item in parsed.get("evidence") or []
            ][:8],
            suspected_component=component,
            confidence=float(parsed.get("confidence") or 0.0),
            mismatch=str(parsed.get("mismatch") or ""),
            general_principle=str(
                parsed.get("general_principle") or ""
            ),
        )


class AnalysisPipeline:
    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()
        self.store = EvidenceStore(self.repo)
        self.local = LocalAnalyst()
        self.cloud = CloudAnalyst(self.repo)
        # One explicit analysis cycle shares one bounded, read-only history
        # snapshot across all records it analyzes.
        self._verified_execution_evidence: list[dict[str, Any]] | None = None

    def collect_verified_execution_evidence(
        self,
        *,
        limit: int = 16,
        repository_identity: str | None = None,
        capability_class: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load trusted ordinary execution evidence once per analysis cycle."""
        if self._verified_execution_evidence is None:
            self._verified_execution_evidence = self.store.collect_verified_execution_evidence(
                limit=limit,
                repository_identity=repository_identity,
                capability_class=capability_class,
            )
            # Explicit analysis may accumulate trusted success patterns, but
            # this does not create candidates or grant mutation authority.
            self.store.record_verified_success_patterns(
                self._verified_execution_evidence
            )
            self.store.principles.record_verified_success_principle(
                self._verified_execution_evidence
            )
        return [dict(item) for item in self._verified_execution_evidence]

    @staticmethod
    def _select_final(
        *,
        capability: str,
        deterministic: FeedbackReport,
        blind: FeedbackReport | None,
        cloud: FeedbackReport | None,
    ) -> tuple[FeedbackReport, dict[str, Any]]:
        """Arbitrate analyses without allowing model-driven component drift.

        Objective validation establishes the benchmark capability boundary.
        A model may enrich the diagnosis only when it agrees with the expected
        component. Cross-component observations remain recorded as secondary
        evidence, but cannot authorize a patch for the unrelated component.
        """
        expected_component = CAPABILITY_COMPONENT.get(
            capability,
            deterministic.suspected_component,
        )

        arbitration: dict[str, Any] = {
            "capability": capability,
            "expected_component": expected_component,
            "deterministic_component": (
                deterministic.suspected_component
            ),
            "blind_component": (
                blind.suspected_component
                if blind
                else ""
            ),
            "cloud_component": (
                cloud.suspected_component
                if cloud
                else ""
            ),
            "cloud_accepted": False,
            "decision": "deterministic",
            "disagreement": "",
        }

        if cloud is None:
            arbitration["decision"] = (
                "deterministic_cloud_unavailable"
            )
            return deterministic, arbitration

        if not (
            cloud.suspected_component
            and cloud.general_principle
            and cloud.confidence >= 0.65
        ):
            arbitration["decision"] = (
                "deterministic_cloud_incomplete"
            )
            return deterministic, arbitration

        if (
            expected_component
            and cloud.suspected_component
            != expected_component
        ):
            arbitration["decision"] = (
                "deterministic_component_guard"
            )
            arbitration["disagreement"] = (
                "Cloud analysis selected "
                f"{cloud.suspected_component!r}, but objective "
                f"capability {capability!r} is bounded to "
                f"{expected_component!r}."
            )

            # Preserve useful cloud observations without allowing component
            # reassignment or cross-component patch authorization.
            deterministic.evidence.extend(
                [
                    (
                        "cloud_secondary_summary="
                        + cloud.summary
                    ),
                    (
                        "cloud_secondary_component="
                        + cloud.suspected_component
                    ),
                    (
                        "cloud_secondary_mismatch="
                        + cloud.mismatch
                    ),
                ]
            )

            return deterministic, arbitration

        arbitration["cloud_accepted"] = True
        arbitration["decision"] = "cloud_grounded"

        # Keep the objective component authoritative even when the model agrees.
        cloud.suspected_component = (
            expected_component
            or cloud.suspected_component
        )

        return cloud, arbitration

    def analyze_path(
        self,
        path: Path,
        *,
        use_local: bool = True,
        use_cloud: bool = True,
    ) -> dict[str, Any]:
        record = self.store.read(path)

        deterministic = deterministic_analysis(record)

        blind = (
            self.local.analyze(record)
            if use_local
            else None
        )

        cloud = (
            self.cloud.analyze(
                record,
                blind=blind,
                deterministic=deterministic,
            )
            if use_cloud
            else None
        )

        task = record.get("task") or {}
        capability = str(
            task.get("capability") or ""
        )

        final, arbitration = self._select_final(
            capability=capability,
            deterministic=deterministic,
            blind=blind,
            cloud=cloud,
        )

        verified_execution_evidence = self.collect_verified_execution_evidence(
            capability_class=capability or None,
        )

        learned = (
            self.store.principles.record_failure_principle(
                component=final.suspected_component,
                capability=str(task.get("capability") or ""),
                principle=final.general_principle,
                task_id=str(task.get("task_id") or path.stem),
                confidence=final.confidence,
                evidence=final.evidence + [final.mismatch],
            )
            if (
                final.suspected_component
                and final.general_principle
            )
            else None
        )

        record["analysis_pipeline"] = {
            "version": ANALYSIS_VERSION,
            "analyzed_at": _now(),
            "local_available": self.local.available(),
            "cloud_available": self.cloud.available(),
            "deterministic": asdict(deterministic),
            "blind": (
                asdict(blind)
                if blind
                else None
            ),
            "cloud": (
                asdict(cloud)
                if cloud
                else None
            ),
            "final": asdict(final),
            "arbitration": arbitration,
            "principle": learned,
            "synthesized": learned is not None,
            # Structured trusted history is analysis input only; it does not
            # authorize candidate generation or mutation.
            "verified_execution_evidence": verified_execution_evidence,
        }

        record["status"] = (
            "principle_recurrent"
            if learned
            and learned.get("status") == "recurrent"
            else "principle_candidate"
            if learned
            else "analysis_incomplete"
        )

        self.store.write(path, record)

        return record

    def analyze_pending(
        self,
        *,
        limit: int = 0,
        use_local: bool = True,
        use_cloud: bool = True,
    ) -> list[dict[str, Any]]:
        results = []

        for path in self.store.pending(limit=limit):
            results.append(
                self.analyze_path(
                    path,
                    use_local=use_local,
                    use_cloud=use_cloud,
                )
            )

        return results
