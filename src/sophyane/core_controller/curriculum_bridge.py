"""Durable bridge from bounded learning evidence to next curriculum tasks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sophyane.rsi.curriculum import (
    CurriculumPolicy,
    CurriculumStore,
    CurriculumTask,
    CurriculumScheduler,
    ResourceClass,
    TaskSource,
)


class ObservationCurriculumBridge:
    """Turn accepted observations into durable, reviewable next tasks.

    This does not grant mutation authority and does not claim an LLM approved
    the task. The task is a bounded follow-up candidate for the RSI scheduler.
    An LLM reviewer may later approve, reject, or refine it.
    """

    def __init__(self, path: Path):
        self.store = CurriculumStore(path)
        self.scheduler = CurriculumScheduler(self.store, CurriculumPolicy())

    def enqueue_observation(self, observation: Any) -> tuple[bool, str]:
        fingerprint = str(observation.fingerprint)
        task_id = "observation-" + fingerprint[:24]
        component = str(observation.component).strip() or "sophyane"
        problem = str(observation.problem).strip()
        objective = f"Investigate and improve {component}: {problem}"
        component_paths = {
            "provider_gateway": "src/sophyane/core_controller/provider_gateway.py",
            "core_controller": "src/sophyane/core_controller/controller.py",
            "curriculum": "src/sophyane/rsi/curriculum.py",
            "sophyane.core_controller": "src/sophyane/core_controller/",
        }
        editable_path = component_paths.get(component, "src/sophyane/")
        test_paths = {
            "provider_gateway": "tests/test_core_controller_provider_gateway.py",
            "core_controller": "tests/test_core_controller_integration.py",
            "curriculum": "tests/rsi/test_curriculum_scheduler.py",
        }
        test_path = test_paths.get(component, "tests/test_core_controller_host_runtime.py")
        task = CurriculumTask(
            task_id=task_id,
            parent_ability_id="runtime-observation",
            objective=objective[:2000],
            editable_paths=(editable_path,),
            verification=(f"PYTHONPATH=src .venv/bin/pytest -q {test_path}",),
            source=TaskSource.WEAKNESS,
            resource_class=ResourceClass.NORMAL,
            component=component[:200],
            review_status="pending",
        )
        return self.scheduler.enqueue(task), task_id

    def pending_tasks(self) -> list[dict[str, Any]]:
        state = self.store.load()
        return [
            {
                "task_id": task.task_id,
                "objective": task.objective,
                "status": task.status.value,
                "review_status": task.review_status,
                "source": task.source.value,
            }
            for task in state.queue
            if task.status.value in {"queued", "paused"}
        ]


def default_curriculum_bridge() -> ObservationCurriculumBridge:
    path = Path(
        os.environ.get(
            "SOPHYANE_CURRICULUM_STATE",
            ".sophyane-state/curriculum.json",
        )
    ).expanduser()
    return ObservationCurriculumBridge(path)


__all__ = ["ObservationCurriculumBridge", "default_curriculum_bridge"]
