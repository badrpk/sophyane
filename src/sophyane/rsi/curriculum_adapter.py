"""Bridge bounded curriculum tasks into the existing autonomous RSI pipeline."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from .curriculum import CurriculumTask
from .weakness_ledger import WeaknessRecord, WeaknessStatus


class NativeEvolutionTaskAdapter:
    """Run one bounded cycle of Sophyane's native promotion engine."""

    def __init__(self, repository, *, timeout_seconds: int = 300, engine_factory=None, promotion_manager=None):
        self.repository = repository
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.engine_factory = engine_factory
        self.promotion_manager = promotion_manager

    def run_task(self, task: CurriculumTask) -> dict[str, object]:
        from sophyane.evolution.models import EvolutionConfig

        factory = self.engine_factory
        if factory is None:
            from sophyane.evolution.engine import EvolutionEngine
            factory = EvolutionEngine
        capability = str(getattr(task, "component", "") or "")
        # Curriculum components may be experiment identifiers (for example
        # ``demo_score``), while EvolutionEngine consumes validator capability
        # names. Keep the durable task compatible with both contracts.
        if capability == "demo_score":
            capability = "filesystem"
        config = EvolutionConfig(
            repo=self.repository,
            initial_capability=capability,
            cycles=1,
            timeout_seconds=self.timeout_seconds,
            allow_cloud_analysis=True,
            allow_candidate_patches=True,
            allow_promotion=True,
        )
        try:
            records = factory(config).run()
        except Exception as error:
            return {"status": "paused", "reason": f"native evolution failed: {error}"}
        if not records:
            return {"status": "rejected", "reason": "native evolution returned no record"}
        record = records[-1]
        gate = getattr(record, "gate", None)
        details = dict(getattr(gate, "details", {}) or {}) if gate else {}
        promoted = bool(details.get("promotion_committed"))
        native_status = str(getattr(record, "status", ""))
        evidence = (
            f"native_status={native_status}; "
            f"promotion_committed={promoted}; "
            f"run_id={getattr(record, 'run_id', '')}"
        )
        if not promoted:
            return {"status": "rejected", "reason": evidence}
        if self.promotion_manager is None:
            return {"status": "rejected", "reason": evidence + "; live promotion manager unavailable"}
        candidate_commit = str(details.get("candidate_commit") or "")
        expected_base = str(details.get("base_commit") or "")
        if not candidate_commit or not expected_base:
            return {"status": "rejected", "reason": evidence + "; native commit evidence unavailable"}
        live = self.promotion_manager.promote(candidate_commit, expected_base=expected_base)
        live_evidence = f"live_promoted={bool(getattr(live, 'promoted', False))}; active_commit={getattr(live, 'active_commit', '')}"
        if getattr(live, "promoted", False):
            return {"status": "verified", "evidence": (evidence, live_evidence), "ability": task.task_id, "checkpoint": expected_base}
        return {"status": "rejected", "reason": evidence + "; " + live_evidence + "; " + str(getattr(live, "reason", "promotion rejected"))}


class AutonomousCurriculumTaskAdapter:
    """Run curriculum tasks using the controller's existing RSI gates.

    The adapter creates only a diagnostic weakness record. The controller
    remains responsible for candidate isolation, providers, verification,
    promotion, rollback, and persistence of the accepted result.
    """

    def __init__(self, controller: Any, *, max_cycles: int = 64, clock=time.time):
        self.controller = controller
        self.max_cycles = max(1, int(max_cycles))
        self.clock = clock

    def _component(self, task: CurriculumTask) -> str:
        component = str(getattr(task, "component", "") or "").strip()
        plans = getattr(self.controller, "plans", {})
        if component:
            return component
        if len(plans) == 1:
            return next(iter(plans))
        return ""

    def run_task(self, task: CurriculumTask) -> dict[str, object]:
        ledger = getattr(self.controller, "ledger", None)
        plans = getattr(self.controller, "plans", {})
        tick = getattr(self.controller, "tick", None)
        if ledger is None or not callable(tick):
            return {"status": "paused", "reason": "autonomous RSI controller is incomplete"}

        component = self._component(task)
        plan = plans.get(component)
        if not component or plan is None:
            return {"status": "rejected", "reason": "curriculum task has no frozen experiment plan"}
        allowed_paths = frozenset(getattr(plan, "allowed_paths", ()))
        if not set(task.editable_paths).issubset(allowed_paths):
            return {"status": "rejected", "reason": "task paths are outside the frozen plan allowed paths"}

        fingerprint = hashlib.sha256(("curriculum:" + task.task_id).encode()).hexdigest()
        record = ledger.records.get(fingerprint)
        if record is None:
            record = WeaknessRecord(
                fingerprint=fingerprint,
                problem=task.objective[:2000],
                component=component,
                evidence=[str(item)[:2000] for item in task.verification[:32]],
                sources=["curriculum"],
                confidence=1.0,
                first_seen=self.clock(),
            )
            ledger.records[fingerprint] = record
            ledger.save()
        elif record.status == WeaknessStatus.ACCEPTED.value:
            return {"status": "verified", "evidence": tuple(record.evidence), "ability": task.task_id}

        for _ in range(self.max_cycles):
            try:
                tick()
            except Exception as error:
                return {"status": "paused", "reason": f"RSI task execution failed: {error}"}
            if record.status == WeaknessStatus.ACCEPTED.value:
                return {"status": "verified", "evidence": tuple(record.evidence), "ability": task.task_id}
            if record.status == WeaknessStatus.REJECTED.value:
                return {"status": "rejected", "reason": record.rejection_history[-1] if record.rejection_history else "RSI rejected task"}
        return {"status": "paused", "reason": f"RSI task exceeded {self.max_cycles} cycles"}
