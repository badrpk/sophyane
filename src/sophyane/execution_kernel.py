"""Canonical orchestration boundary for Sophyane execution.

Sprint 1 intentionally preserves the proven adaptive runtime.  The kernel gives every
entry point one stable place to invoke execution while later routing, memory,
verification and reward components are migrated behind this interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import time
import uuid

Progress = Callable[[str], None]
StructuredRunner = Callable[..., str]


@dataclass(slots=True)
class ExecutionRequest:
    """Normalized request accepted by :class:`ExecutionKernel`."""

    initial_text: str
    original_request: str
    ask: Callable[[str], Any]
    workspace: Path
    max_steps: int = 12
    progress: Progress = field(default=lambda _message: None, repr=False)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass(slots=True)
class ExecutionResult:
    """Observable outcome of one kernel run."""

    task_id: str
    text: str
    workspace: Path
    elapsed_seconds: float


class ExecutionKernel:
    """Single compatibility-first orchestration entry point.

    The injected runner remains responsible for provider interaction and concrete
    execution during Sprint 1.  This class owns request normalization, workspace
    preparation, lifecycle reporting and the stable public boundary used by the TUI.
    """

    def __init__(self, runner: StructuredRunner) -> None:
        self._runner = runner
        self.last_result: ExecutionResult | None = None

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        workspace = request.workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        request.progress(f"Kernel task {request.task_id}: workspace {workspace}")
        started = time.monotonic()
        text = self._runner(
            initial_text=request.initial_text,
            original_request=request.original_request,
            ask=request.ask,
            workspace=workspace,
            max_steps=request.max_steps,
            progress=request.progress,
        )
        result = ExecutionResult(
            task_id=request.task_id,
            text=str(text),
            workspace=workspace,
            elapsed_seconds=time.monotonic() - started,
        )
        self.last_result = result
        request.progress(
            f"Kernel task {request.task_id}: finished in {result.elapsed_seconds:.2f}s"
        )
        return result

    def run_structured_loop(
        self,
        *,
        initial_text: str,
        original_request: str,
        ask: Callable[[str], Any],
        workspace: Path | None = None,
        max_steps: int = 12,
        progress: Progress | None = None,
    ) -> str:
        """Drop-in replacement for the legacy ``run_structured_loop`` callable."""

        request = ExecutionRequest(
            initial_text=initial_text,
            original_request=original_request,
            ask=ask,
            workspace=(workspace or Path.cwd()),
            max_steps=max_steps,
            progress=progress or (lambda _message: None),
        )
        return self.run(request).text
