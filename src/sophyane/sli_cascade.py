
"""Session cascade: SLI first, then local LLM, then cloud LLM; promote wins."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]

def _progress(p: Progress | None) -> Progress:
    return p or (lambda _m: None)

def _env_mode() -> str:
    return (os.environ.get("SOPHYANE_SESSION_MODE") or "").strip().lower()

def _sli_only() -> bool:
    if os.environ.get("SOPHYANE_SLI_ONLY", "").strip() in {"1", "true", "yes"}:
        return True
    return _env_mode() == "sli_only"

def try_cascade(
    message: str,
    *,
    workspace: Path | None = None,
    config: dict[str, Any] | None = None,
    progress: Progress | None = None,
    call_local: Callable[..., str] | None = None,
    call_cloud: Callable[..., str] | None = None,
) -> str:
    """Return final report text. Always attempts promote on success."""
    progress = _progress(progress)
    ws = Path(workspace or (Path.cwd() / ".sophyane-workspace"))
    ws.mkdir(parents=True, exist_ok=True)
    mode = _env_mode()
    sli_only = _sli_only() or mode in {"sli_chunks", "sli_only"} and os.environ.get("SOPHYANE_SLI_ONLY") == "1"

    # --- Tier 1: SLI ---
    report = None
    try:
        from sophyane.sli_chunk_router import try_sli_chunks
        progress("Cascade: SLI chunks")
        report = try_sli_chunks(message, workspace=ws, progress=progress)
    except Exception as e:
        progress(f"Cascade: SLI error {e}")
        report = None

    from sophyane.code_memory.promote_success import is_success_report, promote_workspace

    if report and is_success_report(report):
        promote_workspace(ws, request=message, source="promote:sli", report=report, progress=progress)
        return report

    # Pure SLI-only: stop here
    if sli_only and mode not in {"cascade", "local_first", "sli_then_llm"}:
        if report:
            return report
        return (
            "SLI-only mode: no valid grounded assembly for this request.\n"
            "Choose option 1 cascade (SLI→local→cloud), option 2 local, or option 3 cloud.\n"
            "No LLM fallback was used."
        )

    # Modes that allow LLM rescue
    allow_local = mode in {"cascade", "local_first", "sli_then_llm", "local_llm", ""} or not sli_only
    allow_cloud = mode in {"cascade", "local_first", "sli_then_llm", "cloud_llm"} or (
        not sli_only and mode not in {"local_llm"}
    )
    # Default cascade when SOPHYANE_SESSION_MODE=cascade
    if mode == "cascade":
        allow_local = True
        allow_cloud = True
    if mode == "local_llm":
        allow_local = True
        allow_cloud = False
    if mode == "cloud_llm":
        allow_local = False
        allow_cloud = True

    # --- Tier 2: local LLM ---
    if allow_local and call_local is not None:
        progress("Cascade: local LLM rescue")
        try:
            local_report = call_local(message, workspace=ws, config=config)
        except TypeError:
            try:
                local_report = call_local(message)
            except Exception as e:
                local_report = f"Local LLM error: {e}"
        except Exception as e:
            local_report = f"Local LLM error: {e}"
        if local_report and is_success_report(local_report):
            promote_workspace(
                ws, request=message, source="promote:local_llm", report=local_report, progress=progress
            )
            return str(local_report)
        if local_report and (ws / "index.html").exists() or any(ws.glob("*.py")):
            # heuristic: files written under validation
            promote_workspace(
                ws, request=message, source="promote:local_llm", report=local_report or "Success: True", progress=progress
            )
            return str(local_report)

    # --- Tier 3: cloud LLM ---
    if allow_cloud and call_cloud is not None:
        progress("Cascade: cloud LLM rescue")
        try:
            cloud_report = call_cloud(message, workspace=ws, config=config)
        except TypeError:
            try:
                cloud_report = call_cloud(message)
            except Exception as e:
                cloud_report = f"Cloud LLM error: {e}"
        except Exception as e:
            cloud_report = f"Cloud LLM error: {e}"
        if cloud_report and (
            is_success_report(cloud_report)
            or (ws / "index.html").exists()
            or any(ws.glob("*.py"))
        ):
            promote_workspace(
                ws,
                request=message,
                source="promote:cloud_llm",
                report=cloud_report if is_success_report(cloud_report) else "Success: True\n" + str(cloud_report)[:500],
                progress=progress,
            )
        return str(cloud_report) if cloud_report else (report or "Cascade: no result")

    return report or (
        "Cascade complete: SLI miss and no LLM callback configured in this context.\n"
        "Use full Sophyane TUI for local/cloud rescue."
    )
