
"""Promote validated artifacts into SLI code memory (any mode)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]

def _progress(p: Progress | None) -> Progress:
    return p or (lambda _m: None)

def is_success_report(report: str | None) -> bool:
    if not report:
        return False
    low = str(report).lower()
    if "success: true" in low:
        return True
    if "success: false" in low or "no llm fallback was used" in low and "success: true" not in low:
        # careful: many failures also say no llm
        pass
    if re.search(r"\bsuccess\b.*\btrue\b", low):
        return True
    return False

def promote_workspace(
    workspace: Path | str,
    *,
    request: str = "",
    source: str = "promote:success",
    report: str | None = None,
    progress: Progress | None = None,
) -> dict:
    """Ingest files from a successful run into ChunkStore + weight bump."""
    progress = _progress(progress)
    ws = Path(workspace)
    out = {
        "ok": False,
        "files_scanned": 0,
        "chunks_added": 0,
        "reason": "",
    }
    if not ws.is_dir():
        out["reason"] = "no-workspace"
        return out
    if report is not None and not is_success_report(report):
        # still allow explicit promote when caller knows success
        if not any(ws.glob("*.py")) and not any(ws.glob("*.html")):
            out["reason"] = "not-success-report"
            return out
    try:
        from sophyane.code_memory.acquire import acquire_tree
        from sophyane.code_memory.store import ChunkStore
        from sophyane.code_memory.learner import apply_outcome
    except Exception as e:
        out["reason"] = f"import:{e}"
        return out

    try:
        rep = acquire_tree(
            ws,
            source=source,
            progress=progress,
            limit_files=80,
            limit_chunks=120,
        )
        if isinstance(rep, dict):
            out["files_scanned"] = int(rep.get("files_scanned") or 0)
            out["chunks_added"] = int(rep.get("chunks_added") or 0)
        store = ChunkStore()
        # mild weight bump on newest ids if learner supports used-list empty → skip
        out["ok"] = True
        out["memory"] = len(store.ids)
        out["reason"] = "promoted"
        progress(
            f"SLI promote: +{out['chunks_added']} chunks "
            f"(memory={out.get('memory')}) source={source}"
        )
    except Exception as e:
        out["reason"] = f"error:{e}"
        progress(f"SLI promote error: {e}")
    return out

# SOPHYANE_PROMOTION_VALIDATION_GATE_V1
import inspect as _promotion_inspect

from sophyane.code_memory.promotion_gate import (
    validate_workspace_for_promotion as _validate_promotion,
)


_promote_workspace_before_validation_gate = promote_workspace


def promote_workspace(
    *args,
    **kwargs,
):
    signature = _promotion_inspect.signature(
        _promote_workspace_before_validation_gate
    )

    try:
        bound = signature.bind_partial(
            *args,
            **kwargs,
        )

        arguments = dict(
            bound.arguments
        )
    except TypeError:
        arguments = {}

    workspace = (
        arguments.get("workspace")
        or arguments.get("root")
        or arguments.get("path")
        or kwargs.get("workspace")
        or kwargs.get("root")
        or (
            args[0]
            if args
            else None
        )
    )

    report = (
        arguments.get("report")
        or arguments.get("result")
        or kwargs.get("report")
        or kwargs.get("result")
        or ""
    )

    request = (
        arguments.get("request")
        or arguments.get("instruction")
        or kwargs.get("request")
        or kwargs.get("instruction")
        or ""
    )

    progress = (
        arguments.get("progress")
        or kwargs.get("progress")
        or (
            lambda _message:
                None
        )
    )

    if workspace is None:
        return {
            "ok":
                False,

            "reason":
                "promotion blocked: workspace argument was not resolved",

            "files_scanned":
                0,

            "chunks_added":
                0,
        }

    validation = _validate_promotion(
        workspace,
        report=report,
        request=request,
    )

    if not validation.ok:
        progress(
            "SLI promotion blocked: "
            + validation.reason
        )

        return {
            "ok":
                False,

            "reason":
                validation.reason,

            "files_scanned":
                0,

            "chunks_added":
                0,

            "validation_checks":
                list(
                    validation.checks
                ),

            "product_files":
                list(
                    validation.files
                ),
        }

    progress(
        "SLI promotion gate passed: "
        + "; ".join(
            validation.checks
        )
    )

    return _promote_workspace_before_validation_gate(
        *args,
        **kwargs,
    )
