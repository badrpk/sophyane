"""Sophyane SLI Graph — no LLM, recursion-safe, evidence-gated."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]
_GRAPH_DEPTH = 0


def _p(progress: Progress | None) -> Progress:
    return progress or (lambda _m: None)


@dataclass
class SLIState:
    request: str
    workspace: str
    route: str = ""
    report: str = ""
    success: bool = False
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    promoted: bool = False
    chunks_added: int = 0
    seconds: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def log(self, msg: str) -> None:
        self.trace.append(msg)


def classify(state: SLIState, progress: Progress) -> SLIState:
    q = (state.request or "").lower()
    progress(f"SLI-graph: classify «{state.request[:80]}»")

    if any(
        key in q
        for key in (
            "website on",
            "website about",
            "website for",
            "webpage about",
            "webpage on",
            "informational site",
            "site on ",
            "site about ",
        )
    ):
        state.route = "topic_site"
    else:
        try:
            from sophyane.sli_harness_orchestrator import (
                is_harness_execution_request,
            )

            if is_harness_execution_request(state.request):
                state.route = "harness_execution"
            elif any(
                key in q
                for key in (
                    "python file",
                    "audit_chain",
                    "append_event",
                    "verify_chain",
                    "safe_members",
                    "implement ",
                    "fastapi",
                    "policy_engine",
                )
            ):
                state.route = "python_harness"
            elif any(key in q for key in ("ping pong", "pong", "snake", "game", "canvas")):
                state.route = "action_or_internet"
            elif any(key in q for key in ("missing word", "missing letter", "quiz", "cloze")):
                state.route = "language_or_internet"
            else:
                state.route = "memory_then_internet"
        except Exception as error:
            state.errors.append(f"classify-harness:{error}")
            state.route = "memory_then_internet"

    progress(f"SLI-graph: route={state.route}")
    state.log(f"route={state.route}")
    return state


def _ok(state: SLIState) -> None:
    """Accept success only from an explicit validated success report."""

    state.success = "success: true" in (state.report or "").lower()
    workspace = Path(state.workspace)
    if workspace.is_dir():
        state.files = [str(path) for path in workspace.rglob("*") if path.is_file()]


def try_harness_execution(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state

    progress("SLI-graph: evidence-gated unified harness")
    try:
        from sophyane.sli_harness_orchestrator import run_harness_execution

        state.report = str(
            run_harness_execution(
                state.request,
                Path(state.workspace),
                progress=progress,
            )
            or ""
        )
        _ok(state)
        state.log(f"harness success={state.success}")
    except Exception as error:
        state.errors.append(f"harness:{error}")
        progress(f"SLI-graph harness error: {error}")
    return state


def try_memory_router(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state

    progress("SLI-graph: memory/router (no re-entry)")
    previous = os.environ.get("SOPHYANE_SLI_GRAPH")
    os.environ["SOPHYANE_SLI_GRAPH"] = "0"
    try:
        module = __import__("sophyane.sli_chunk_router", fromlist=["*"])
        function = getattr(module, "_sli_try_chunks_before_graph", None) or module.try_sli_chunks
        state.report = str(
            function(
                state.request,
                workspace=Path(state.workspace),
                progress=progress,
            )
            or ""
        )
        _ok(state)
        state.log(f"router success={state.success}")
    except Exception as error:
        state.errors.append(f"router:{error}")
        progress(f"SLI-graph router error: {error}")
    finally:
        if previous is None:
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
        else:
            os.environ["SOPHYANE_SLI_GRAPH"] = previous
    return state


def try_topic(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state

    progress("SLI-graph: rich topic-site orchestration")
    try:
        rich = __import__("sophyane.code_memory.sli_rich_site_compose", fromlist=["*"])
        is_topic = getattr(rich, "is_topic_site_request", lambda _request: True)
        if not is_topic(state.request):
            return state
        function = getattr(rich, "compose_rich_topic_site", None)
        if function is not None:
            output = function(state.request, Path(state.workspace), progress=progress)
            state.report = str(output[0] if isinstance(output, tuple) else output or "")
            _ok(state)
            state.log(f"rich-topic success={state.success}")
            if state.success:
                return state
    except Exception as error:
        state.errors.append(f"rich-topic:{error}")
        progress(f"SLI-graph rich topic error: {error}; using safe topic fallback")

    try:
        module = __import__("sophyane.code_memory.topic_site_compose", fromlist=["*"])
        is_topic = getattr(module, "is_topic_site_request", lambda _request: True)
        if not is_topic(state.request):
            return state
        function = getattr(module, "compose_topic_site", None) or getattr(module, "handle_topic_site", None)
        if function is None:
            return try_memory_router(state, progress)
        try:
            output = function(state.request, Path(state.workspace), progress=progress)
        except TypeError:
            output = function(state.request, workspace=Path(state.workspace), progress=progress)
        state.report = str(output[0] if isinstance(output, tuple) else output or "")
        _ok(state)
        state.log(f"topic-fallback success={state.success}")
    except Exception as error:
        state.errors.append(f"topic:{error}")
        progress(f"SLI-graph topic fallback error: {error}")
    return state


def try_python_harness(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state

    progress("SLI-graph: python harness")
    try:
        from sophyane.code_memory.python_harness_compose import (
            compose_python_harness_request,
        )

        try:
            output = compose_python_harness_request(
                state.request,
                Path(state.workspace),
                progress=progress,
            )
        except TypeError:
            output = compose_python_harness_request(
                state.request,
                workspace=Path(state.workspace),
                progress=progress,
            )
        state.report = str(output[0] if isinstance(output, tuple) else output or "")
        _ok(state)
        state.log(f"python success={state.success}")
    except Exception as error:
        state.errors.append(f"python:{error}")
        progress(f"SLI-graph python error: {error}")
    return state


def try_internet(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state

    progress("SLI-graph: internet acquire")
    try:
        from sophyane.code_memory.internet_acquire import acquire_and_build

        try:
            report = acquire_and_build(
                state.request,
                workspace=Path(state.workspace),
                progress=progress,
            )
        except TypeError:
            report = acquire_and_build(state.request, Path(state.workspace), progress)
        state.report = str(report or "")
        _ok(state)
        state.log(f"internet success={state.success}")
    except Exception as error:
        state.errors.append(f"internet:{error}")
        progress(f"SLI-graph internet error: {error}")
    return state


def validate_and_promote(state: SLIState, progress: Progress) -> SLIState:
    if not state.success:
        return state

    progress("SLI-graph: promote")
    try:
        from sophyane.code_memory.promote_success import (
            is_success_report,
            promote_workspace,
        )

        report = state.report
        if not is_success_report(report):
            state.errors.append("promotion-blocked: report is not a validated success report")
            progress("SLI-graph: promotion blocked; success report was not validated")
            return state

        result = promote_workspace(
            Path(state.workspace),
            request=state.request,
            source="promote:sli_graph",
            report=report,
            progress=progress,
        )
        state.promoted = bool(result.get("ok"))
        state.chunks_added = int(result.get("chunks_added") or 0)
    except Exception as error:
        state.errors.append(f"promote:{error}")
        progress(f"SLI-graph promote error: {error}")
    return state


def run_sli_graph(
    request: str,
    workspace: Path | str | None = None,
    *,
    progress: Progress | None = None,
    max_retries: int = 2,
) -> SLIState:
    global _GRAPH_DEPTH
    progress = _p(progress)

    if _GRAPH_DEPTH > 0:
        progress("SLI-graph: blocked recursive entry")
        state = SLIState(request=request, workspace=str(workspace or "."))
        state.report = "Success: False\nrecursive-entry-blocked\n"
        state.errors.append("recursive-entry-blocked")
        return state

    _GRAPH_DEPTH += 1
    started = time.perf_counter()
    try:
        root = Path(workspace or (Path.cwd() / ".sophyane-workspace"))
        root.mkdir(parents=True, exist_ok=True)
        state = SLIState(request=request, workspace=str(root))
        state = classify(state, progress)

        pipelines = {
            "topic_site": [try_topic, try_memory_router, try_internet],
            "harness_execution": [
                try_harness_execution,
                try_python_harness,
                try_memory_router,
                try_internet,
            ],
            "python_harness": [try_python_harness, try_harness_execution, try_memory_router],
            "language_or_internet": [try_memory_router, try_internet],
            "action_or_internet": [try_memory_router, try_internet],
            "memory_then_internet": [try_memory_router, try_internet],
        }
        steps = pipelines.get(state.route, [try_memory_router, try_internet])

        for attempt in range(max(1, max_retries)):
            progress(f"SLI-graph: attempt {attempt + 1}/{max_retries}")
            for step in steps:
                state = step(state, progress)
                if state.success:
                    break
            if state.success:
                break

        state = validate_and_promote(state, progress)
        state.seconds = round(time.perf_counter() - started, 3)
        if state.report and "SLI-graph route:" not in state.report:
            state.report = (
                state.report.rstrip()
                + f"\nSLI-graph route: {state.route}; seconds: {state.seconds}; "
                f"promoted: {state.promoted}; chunks_added: {state.chunks_added}\n"
            )
        progress(f"SLI-graph done success={state.success} in {state.seconds}s")
        return state
    finally:
        _GRAPH_DEPTH = max(0, _GRAPH_DEPTH - 1)


def try_sli_graph(message: str, workspace=None, progress=None) -> str | None:
    return run_sli_graph(message, workspace=workspace, progress=progress).report
