"""Opt-in continuous RSI curriculum orchestration."""

from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
from typing import Any

from .curriculum import AbilityRecord, CurriculumScheduler, CurriculumStore, TaskStatus
from .curriculum_proposals import ProposalContext, ProposalResult
from .autonomy_policy import FailureClass, classify_failure


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
        self._reconcile_demo_frontier()
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
        live_commit = ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=live_root, capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                live_commit = result.stdout.strip()
        except OSError:
            pass
        recorded_commit = str(promotion["active_commit"]).strip()
        scoped = bool(promotion.get("task_id") or promotion.get("repository_id"))
        if scoped and live_commit != recorded_commit:
            return 0
        if not scoped and live_commit and live_commit != recorded_commit:
            return 0
        state = self.store.load()
        reconciled = 0
        evidence_prefix = f"reconciled promoted live snapshot {recorded_commit}"
        for task in state.queue:
            if task.status not in {TaskStatus.QUEUED, TaskStatus.PAUSED} or not task.proposal_files:
                continue
            if scoped and (task.task_id != promotion.get("task_id")
                           or task.repository_id != promotion.get("repository_id")
                           or task.base_commit != promotion.get("base_commit")
                           or recorded_commit != promotion.get("candidate_commit")):
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

    def _reconcile_demo_frontier(self) -> bool:
        """Recover a missed frontier transition after a verified promotion.

        The worker can be killed between recording ``task_verified`` and
        advancing the host-owned challenge.  On the next start, reconcile the
        newest verified demo task so progress does not depend on one callback
        completing in one process lifetime.
        """
        state = self.store.load()
        verified = [task for task in state.queue if task.status is TaskStatus.VERIFIED]
        if not verified:
            return False
        return self._advance_demo_frontier(verified[-1])

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

    def _advance_demo_frontier(self, task) -> bool:
        """Prepare the next host-owned frozen challenge after a verified step.

        This changes only the deterministic demo fixture's challenge marker and
        checks.  It never accepts model output as policy, commands, or an
        editable path; the next candidate must still pass the full RED/GREEN
        and promotion gates.
        """
        owner = getattr(self.controller, "controller", self.controller)
        if "demo_score" not in getattr(owner, "plans", {}):
            return False
        marker = str(owner.plans["demo_score"].expected_failure)
        match = re.search(r"_v(\d+)$", marker)
        if not match:
            return False
        current = int(match.group(1))
        target_match = re.search(r"returning exactly (\d+)", str(task.objective))
        if not target_match or int(target_match.group(1)) != current:
            return False
        target = current + 1
        root = self.state_dir / "live-worktree"
        scripts = {
            "tools/rsi_demo_red.py": [(r"score\(\) == \d+", f"score() == {target}"),
                                      (r"demo_score_v\d+", f"demo_score_v{target}")],
            "tools/rsi_demo_holdout.py": [(r"score\(\) >= \d+", f"score() >= {target}"),],
            "tools/rsi_demo_regression.py": [(r"score\(\) >= \d+", f"score() >= {target}"),],
            "tools/rsi_demo_meta.py": [(r"score\(\) == \d+", f"score() == {target}"),],
        }
        replacements = {}
        for relative, substitutions in scripts.items():
            path = root / relative
            text = path.read_text(encoding="utf-8")
            for pattern, replacement in substitutions:
                text = re.sub(pattern, replacement, text)
            replacements[path] = text
        policy_path = self.state_dir / "experiments.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["demo_score"]["expected_failure"] = f"RSI_WEAKNESS_demo_score_v{target}"
        for path, text in replacements.items():
            path.write_text(text, encoding="utf-8")
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        from dataclasses import replace
        owner.plans["demo_score"] = replace(
            owner.plans["demo_score"],
            expected_failure=f"RSI_WEAKNESS_demo_score_v{target}",
        )
        self.store.append_event({"event": "frontier_advanced", "component": "demo_score", "target": target})
        return True

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
            proposal.task.review_status = (
                "approved" if proposal.review_outcome == "approved" else "pending"
            )
            if self.scheduler.enqueue(proposal.task):
                self.scheduler.mark_follow_up_enqueued()
            else:
                self.store.append_event({"event": "follow_up_rejected", "reason": "scheduler rejected proposal"})

    def _review_pending_tasks(self) -> int:
        """Automatically review generated candidates when intelligence is configured."""
        intelligence = getattr(self, "intelligence", None)
        if intelligence is None:
            return 0
        state = self.store.load()
        reviewed = 0
        for task in state.queue:
            if task.status is not TaskStatus.QUEUED or task.review_status != "pending":
                continue
            ability = AbilityRecord(
                task.parent_ability_id or "runtime-observation",
                task.component or "curriculum improvement",
                (task.objective,),
                task.task_id,
            )
            context = ProposalContext(
                ability=ability,
                allowed_paths=task.editable_paths,
                existing_task_ids=tuple(item.task_id for item in state.queue),
                capability_summary=task.objective,
            )
            try:
                result = intelligence.review(context, ProposalResult(True, task, "candidate"))
            except Exception as error:
                self.store.append_event({"event": "task_review_error", "task_id": task.task_id, "reason": str(error)})
                continue
            if result.review_outcome in {"approved", "rejected"}:
                self.scheduler.record_review(
                    task.task_id,
                    approved=result.review_outcome == "approved",
                    provider=result.reviewers[0] if result.reviewers else "",
                    reason=result.reason,
                )
                reviewed += 1
        return reviewed

    def tick(self) -> dict[str, object]:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.started:
            if not self.start():
                return {"status": "idle", **self.scheduler.status()}
        self._review_pending_tasks()
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
            decision = classify_failure(error, phase="execution")
            if decision.category is FailureClass.SAFETY_HALT:
                self.scheduler.pause(decision.reason)
                halt_path = self.state_dir / "safety-halt.json"
                halt_path.write_text(
                    json.dumps({
                        "state": "safety_halt",
                        "reason": decision.reason[:1000],
                    }, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return {"status": "safety_halt", "reason": decision.reason, "task_id": task.task_id}
            self.scheduler.record_failure(task.task_id, TaskStatus.PAUSED, str(error))
            return {"status": "paused", "reason": str(error), "task_id": task.task_id}

        status = str(result.get("status", "")).lower()
        reason = str(result.get("reason", ""))
        if status in {"rejected", "paused"} and any(marker in reason.casefold() for marker in (
            "sandboxunavailable", "bubblewrap", "user namespaces", "unrestricted execution"
        )):
            self.scheduler.pause(reason)
            halt_path = self.state_dir / "safety-halt.json"
            halt_path.write_text(
                json.dumps({"state": "safety_halt", "reason": reason[:1000]}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return {"status": "safety_halt", "reason": reason, "task_id": task.task_id}
        if status == "verified":
            evidence = tuple(str(item) for item in result.get("evidence", ()))
            self.scheduler.record_verified(task.task_id, evidence)
            self._advance_demo_frontier(task)
            ability = self._record_ability(task, result)
            self._enqueue_follow_up(ability)
            return {"status": "verified", "task_id": task.task_id, "ability_id": ability.ability_id}
        if status == "already_green":
            reason = str(result.get("reason", "RED_ALREADY_GREEN"))
            self.scheduler.record_failure(task.task_id, TaskStatus.REJECTED, reason)
            return {"status": "already_green", "task_id": task.task_id, "reason": reason}
        failure_status = {
            "rejected": TaskStatus.REJECTED,
            "rolled_back": TaskStatus.ROLLED_BACK,
            "paused": TaskStatus.PAUSED,
        }.get(status, TaskStatus.REJECTED)
        reason = reason or "task did not verify"
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
