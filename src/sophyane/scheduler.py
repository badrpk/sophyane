"""Cron-like scheduled agent jobs (local JSON store + due runner)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHED_DIR = Path.home() / ".local" / "state" / "sophyane" / "scheduler"
JOBS_FILE = SCHED_DIR / "jobs.json"


@dataclass
class Job:
    id: str
    name: str
    prompt: str
    every_sec: int
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    skill: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load() -> list[Job]:
    SCHED_DIR.mkdir(parents=True, exist_ok=True)
    if not JOBS_FILE.exists():
        return []
    try:
        raw = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    jobs: list[Job] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            jobs.append(Job(**item))
        except TypeError:
            continue
    return jobs


def _save(jobs: list[Job]) -> None:
    SCHED_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps([j.to_dict() for j in jobs], indent=2) + "\n", encoding="utf-8")


def schedule_job(name: str, prompt: str, every_sec: int = 3600, *, skill: str = "") -> dict[str, Any]:
    jobs = _load()
    now = time.time()
    job = Job(
        id=uuid.uuid4().hex[:12],
        name=name,
        prompt=prompt,
        every_sec=max(60, int(every_sec)),
        next_run=now + max(60, int(every_sec)),
        skill=skill,
    )
    jobs.append(job)
    _save(jobs)
    return {"ok": True, "job": job.to_dict()}


def list_jobs() -> dict[str, Any]:
    jobs = _load()
    return {"ok": True, "jobs": [j.to_dict() for j in jobs], "count": len(jobs)}


def remove_job(job_id: str) -> dict[str, Any]:
    jobs = _load()
    kept = [j for j in jobs if j.id != job_id]
    _save(kept)
    return {"ok": True, "removed": len(jobs) - len(kept)}


def due_jobs(now: float | None = None) -> list[Job]:
    now = now or time.time()
    return [j for j in _load() if j.enabled and j.next_run <= now]


def mark_ran(job_id: str) -> None:
    jobs = _load()
    now = time.time()
    for j in jobs:
        if j.id == job_id:
            j.last_run = now
            j.next_run = now + j.every_sec
    _save(jobs)


def run_due(*, execute: bool = True) -> dict[str, Any]:
    """Run due jobs. execute=True uses expert hybrid answer (safe, no side effects by default)."""
    due = due_jobs()
    results: list[dict[str, Any]] = []
    for job in due:
        entry: dict[str, Any] = {"id": job.id, "name": job.name}
        if execute:
            try:
                from sophyane.expert.answer import answer_tough_question

                system_extra = ""
                if job.skill:
                    from sophyane.skills import get_skill

                    sk = get_skill(job.skill)
                    if sk:
                        system_extra = sk.system
                ans = answer_tough_question(job.prompt, mode="expert")
                entry["ok"] = True
                entry["answer_preview"] = (ans.get("answer") or "")[:500]
                entry["skill"] = job.skill
                if system_extra:
                    entry["skill_applied"] = True
            except Exception as error:  # noqa: BLE001
                entry["ok"] = False
                entry["error"] = str(error)
        else:
            entry["ok"] = True
            entry["dry_run"] = True
        mark_ran(job.id)
        results.append(entry)
    return {"ok": True, "ran": len(results), "results": results}
