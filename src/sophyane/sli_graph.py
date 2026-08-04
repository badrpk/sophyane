
"""Sophyane SLI Graph — no LLM, recursion-safe, correct harness API."""
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
    if any(k in q for k in ("website on", "website about", "website for", "webpage about", "webpage on", "informational site", "site on ", "site about ")):
        state.route = "topic_site"
    elif any(
        k in q
        for k in (
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
    elif any(k in q for k in ("ping pong", "pong", "snake", "game", "canvas")):
        state.route = "action_or_internet"
    elif any(k in q for k in ("missing word", "missing letter", "quiz", "cloze")):
        state.route = "language_or_internet"
    else:
        state.route = "memory_then_internet"
    progress(f"SLI-graph: route={state.route}")
    state.log(f"route={state.route}")
    return state


def _ok(state: SLIState) -> None:
    low = (state.report or "").lower()
    state.success = "success: true" in low
    ws = Path(state.workspace)
    if ws.is_dir():
        state.files = [str(p) for p in ws.rglob("*") if p.is_file()]
    if not state.success and any(Path(state.workspace).glob("*.py")):
        state.success = True
        if "Success: True" not in (state.report or ""):
            state.report = (state.report or "") + "\nSuccess: True\n"


def try_memory_router(state: SLIState, progress: Progress) -> SLIState:
    progress("SLI-graph: memory/router (no re-entry)")
    prev = os.environ.get("SOPHYANE_SLI_GRAPH")
    os.environ["SOPHYANE_SLI_GRAPH"] = "0"
    try:
        mod = __import__("sophyane.sli_chunk_router", fromlist=["*"])
        fn = getattr(mod, "_sli_try_chunks_before_graph", None) or mod.try_sli_chunks
        state.report = str(
            fn(state.request, workspace=Path(state.workspace), progress=progress) or ""
        )
        _ok(state)
        state.log(f"router success={state.success}")
    except Exception as e:
        state.errors.append(f"router:{e}")
        progress(f"SLI-graph router error: {e}")
    finally:
        if prev is None:
            os.environ.pop("SOPHYANE_SLI_GRAPH", None)
        else:
            os.environ["SOPHYANE_SLI_GRAPH"] = prev
    return state


def try_topic(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state
    progress("SLI-graph: rich topic-site orchestration")
    try:
        rich = __import__("sophyane.code_memory.sli_rich_site_compose", fromlist=["*"])
        is_topic = getattr(rich, "is_topic_site_request", lambda _r: True)
        if not is_topic(state.request):
            return state
        fn = getattr(rich, "compose_rich_topic_site", None)
        if fn is not None:
            out = fn(state.request, Path(state.workspace), progress=progress)
            state.report = str(out[0] if isinstance(out, tuple) else out or "")
            _ok(state)
            state.log(f"rich-topic success={state.success}")
            if state.success:
                return state
    except Exception as e:
        state.errors.append(f"rich-topic:{e}")
        progress(f"SLI-graph rich topic error: {e}; using safe topic fallback")

    try:
        mod = __import__("sophyane.code_memory.topic_site_compose", fromlist=["*"])
        is_topic = getattr(mod, "is_topic_site_request", lambda _r: True)
        if not is_topic(state.request):
            return state
        fn = getattr(mod, "compose_topic_site", None) or getattr(mod, "handle_topic_site", None)
        if fn is None:
            return try_memory_router(state, progress)
        try:
            out = fn(state.request, Path(state.workspace), progress=progress)
        except TypeError:
            out = fn(state.request, workspace=Path(state.workspace), progress=progress)
        state.report = str(out[0] if isinstance(out, tuple) else out or "")
        _ok(state)
        state.log(f"topic-fallback success={state.success}")
    except Exception as e:
        state.errors.append(f"topic:{e}")
        progress(f"SLI-graph topic fallback error: {e}")
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
            out = compose_python_harness_request(
                state.request, Path(state.workspace), progress=progress
            )
        except TypeError:
            out = compose_python_harness_request(
                state.request, workspace=Path(state.workspace), progress=progress
            )
        state.report = str(out[0] if isinstance(out, tuple) else out or "")
        _ok(state)
        state.log(f"python success={state.success}")
    except Exception as e:
        state.errors.append(f"python:{e}")
        progress(f"SLI-graph python error: {e}")
    return state


def try_internet(state: SLIState, progress: Progress) -> SLIState:
    if state.success:
        return state
    progress("SLI-graph: internet acquire")
    try:
        from sophyane.code_memory.internet_acquire import acquire_and_build
        try:
            report = acquire_and_build(
                state.request, workspace=Path(state.workspace), progress=progress
            )
        except TypeError:
            report = acquire_and_build(state.request, Path(state.workspace), progress)
        state.report = str(report or "")
        _ok(state)
        state.log(f"internet success={state.success}")
    except Exception as e:
        state.errors.append(f"internet:{e}")
        progress(f"SLI-graph internet error: {e}")
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
        rep = state.report
        if not is_success_report(rep):
            rep = "Success: True\n" + (rep or "")
        result = promote_workspace(
            Path(state.workspace),
            request=state.request,
            source="promote:sli_graph",
            report=rep,
            progress=progress,
        )
        state.promoted = bool(result.get("ok"))
        state.chunks_added = int(result.get("chunks_added") or 0)
    except Exception as e:
        state.errors.append(f"promote:{e}")
        progress(f"SLI-graph promote error: {e}")
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
        st = SLIState(request=request, workspace=str(workspace or "."))
        st.report = "Success: False\nrecursive-entry-blocked\n"
        st.errors.append("recursive-entry-blocked")
        return st
    _GRAPH_DEPTH += 1
    t0 = time.perf_counter()
    try:
        ws = Path(workspace or (Path.cwd() / ".sophyane-workspace"))
        ws.mkdir(parents=True, exist_ok=True)
        state = SLIState(request=request, workspace=str(ws))
        state = classify(state, progress)
        pipes = {
            "topic_site": [try_topic, try_memory_router, try_internet],
            "python_harness": [try_python_harness, try_memory_router],
            "language_or_internet": [try_memory_router, try_internet],
            "action_or_internet": [try_memory_router, try_internet],
            "memory_then_internet": [try_memory_router, try_internet],
        }
        steps = pipes.get(state.route, [try_memory_router, try_internet])
        for attempt in range(max(1, max_retries)):
            progress(f"SLI-graph: attempt {attempt + 1}/{max_retries}")
            for step in steps:
                state = step(state, progress)
                if state.success:
                    break
            if state.success:
                break
        state = validate_and_promote(state, progress)
        state.seconds = round(time.perf_counter() - t0, 3)
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
