"""Parallel scheduler for GoalExecutor."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Iterable

from .goal_execution import GoalExecutor, GoalNode


@dataclass(frozen=True)
class SchedulerStats:
    executed: int
    batches: int


class ParallelGoalScheduler:
    def __init__(self, executor: GoalExecutor, max_workers: int = 4):
        self.executor = executor
        self.max_workers = max_workers

    def _ready_batch(self) -> list[GoalNode]:
        self.executor._refresh_states()

        ready = [
            g
            for g in self.executor.goals.values()
            if g.status.name in {"READY", "FAILED"}
            and self.executor._dependencies_passed(g)
            and g.attempts < g.max_attempts
        ]

        ready.sort(key=lambda g: (g.priority, g.key))

        selected = []
        blocked = set()

        for goal in ready:
            deps = set(goal.dependencies)
            if deps & blocked:
                continue
            blocked.add(goal.key)
            selected.append(goal)

        return selected

    def run(self) -> SchedulerStats:
        batches = 0
        executed = 0

        while True:
            batch = self._ready_batch()
            if not batch:
                break

            batches += 1

            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(batch))
            ) as pool:
                futures = [
                    pool.submit(self.executor.execute_one, goal)
                    for goal in batch
                ]
                wait(futures)

            executed += len(batch)

            if self.executor.achieved():
                break

        return SchedulerStats(executed=executed, batches=batches)
