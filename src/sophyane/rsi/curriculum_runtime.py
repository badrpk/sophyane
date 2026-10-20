"""Opt-in continuous RSI curriculum orchestration."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
from typing import Any

from .curriculum import AbilityRecord, CurriculumScheduler, CurriculumStore, TaskStatus
from .curriculum_proposals import ProposalContext


class ContinuousCurriculumRuntime:
    def __init__(self, state_dir: Path, controller: Any, scheduler: CurriculumScheduler,
                 proposal_adapter: Any = None, *, enabled: bool = False):
        self.state_dir = Path(state_dir)
        self.controller = controller
        self.scheduler = scheduler
        self.proposal_adapter = proposal_adapter
        self.enabled = bool(enabled)
        self.started = False

    @property
    def store(self) -> CurriculumStore:
        return self.scheduler.store

    def start(self) -> bool:
        if not self.enabled:
            return False
        if self.scheduler.status()["stopped"]:
            return False
        self._reconcile_promoted_tasks()
        self.scheduler.resume()
        self.started = True
        return True

    def _reconcile_promoted_tasks(self) -> int:
        """Mark durable tasks complete when their exact proposal is live.

        The promotion manager records a successful live promotion separately
        from curriculum state.  On restart, use that record plus exact file
        equality in the live worktree to bridge the small window between
        promotion and curriculum persistence.  This is intentionally limited
        to queued/restart-paused tasks and never treats an arbitrary checkout
        as promoted.
        """
        promotion_path = self.state_dir / "promotion.json"
        if not promotion_path.is_file():
            return 0
        try:
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return 0
        if not promotion.get("promoted") or not str(promotion.get("active_commit") or "").strip():
            return 0

        live_root = self.state_dir / "live-worktree"
        if not live_root.is_dir():
            return 0
        state = self.store.load()
        reconciled = 0
        promoted_commit = str(promotion["active_commit"])
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=live_root, capture_output=True, text=True, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                promoted_commit = result.stdout.strip()
        except OSError:
            pass
        evidence_prefix = f"reconciled promoted live snapshot {promoted_commit}"
        for task in state.queue:
            if task.status not in {TaskStatus.QUEUED, TaskStatus.PAUSED} or not task.proposal_files:
                continue
            matches = True
            for relative, expected in task.proposal_files.items():
                target = (live_root / relative).resolve()
                try:
                    target.relative_to(live_root.resolve())
                except ValueError:
                    matches = False
                    break
                try:
                    if target.read_text(encoding="utf-8") != expected:
                        matches = False
                        break
                except (OSError, UnicodeError):
                    matches = False
                    break
            if matches and self.scheduler.reconcile_verified(
                task.task_id, (evidence_prefix, "proposal files match live worktree")
            ):
                reconciled += 1
        return reconciled

    def pause(self, reason: str = "operator requested pause") -> bool:
        self.scheduler.pause(reason)
        self.started = False
        return True

    def stop(self, reason: str = "operator requested stop") -> bool:
        self.scheduler.stop(reason)
        self.started = False
        return True

    def _record_ability(self, task, result: dict[str, Any]) -> AbilityRecord:
        state = self.store.load()
        ability_id = str(result.get("ability") or f"ability-{task.task_id}")
        record = AbilityRecord(
            ability_id=ability_id,
            name=task.objective,
            evidence=tuple(str(item) for item in result.get("evidence", ())),
            task_id=task.task_id,
            promoted_checkpoint=str(result.get("checkpoint") or ""),
        )
        state.abilities.append(record)
        self.store.save(state)
        self.store.append_event({"event": "ability_recorded", "ability_id": ability_id, "task_id": task.task_id})
        return record

    def _enqueue_follow_up(self, ability: AbilityRecord) -> None:
        if self.proposal_adapter is None or not self.scheduler.can_enqueue_follow_up():
            return
        state = self.store.load()
        context = ProposalContext(
            ability=ability,
            allowed_paths=tuple(sorted({path for task in state.queue for path in task.editable_paths})),
            existing_task_ids=tuple(task.task_id for task in state.queue),
            capability_summary="verified RSI ability; propose one bounded follow-up",
        )
        proposal = self.proposal_adapter.propose(context)
        intelligence = getattr(self, "intelligence", None)
        if proposal.accepted and intelligence is not None:
            proposal = intelligence.review(context, proposal)
        if proposal.accepted and proposal.task is not None:
            if self.scheduler.enqueue(proposal.task):
                self.scheduler.mark_follow_up_enqueued()
            else:
                self.store.append_event({"event": "follow_up_rejected", "reason": "scheduler rejected proposal"})

    def tick(self) -> dict[str, object]:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.started:
            if not self.start():
                return {"status": "idle", **self.scheduler.status()}
        task = self.scheduler.next_task()
        if task is None:
            return {"status": "idle", **self.scheduler.status()}
        try:
            runner = getattr(self.controller, "run_task", None)
            if not callable(runner):
                raise RuntimeError("curriculum task runner unavailable")
            raw = runner(task)
            result = dict(raw) if isinstance(raw, dict) else {"status": str(raw)}
        except Exception as error:  # scheduler remains durable on controller failure
            self.scheduler.record_failure(task.task_id, TaskStatus.PAUSED, str(error))
            return {"status": "paused", "reason": str(error), "task_id": task.task_id}

        status = str(result.get("status", "")).lower()
        if status == "verified":
            evidence = tuple(str(item) for item in result.get("evidence", ()))
            self.scheduler.record_verified(task.task_id, evidence)
            ability = self._record_ability(task, result)
            self._enqueue_follow_up(ability)
            return {"status": "verified", "task_id": task.task_id, "ability_id": ability.ability_id}
        failure_status = {
            "rejected": TaskStatus.REJECTED,
            "rolled_back": TaskStatus.ROLLED_BACK,
            "paused": TaskStatus.PAUSED,
        }.get(status, TaskStatus.REJECTED)
        reason = str(result.get("reason", "task did not verify"))
        self.scheduler.record_failure(task.task_id, failure_status, reason)
        if self.scheduler.retry(task.task_id, reason):
            return {"status": "retrying", "task_id": task.task_id, "reason": reason}
        return {"status": failure_status.value, "task_id": task.task_id, "reason": result.get("reason", "")}

    def status(self) -> dict[str, object]:
        promotion = {}
        promotion_path = self.state_dir / "promotion.json"
        if promotion_path.is_file():
            try:
                promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                promotion = {"error": "promotion state unreadable"}
        return {"enabled": self.enabled, "started": self.started, "promotion": promotion, **self.scheduler.status()}
