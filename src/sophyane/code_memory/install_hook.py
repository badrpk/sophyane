from __future__ import annotations
from pathlib import Path
from typing import Any
from sophyane.code_memory.generator import generate_from_request
from sophyane.code_memory.learner import apply_outcome
from sophyane.code_memory.store import ChunkStore

def install_code_memory_generator():
    from sophyane import adaptive_execution
    if getattr(adaptive_execution, "_code_memory_installed", False):
        return
    original = getattr(adaptive_execution, "_one_shot_browser_artifact", None)
    def build(*, ask: Any, original_request: str, workspace: Path, progress: Any):
        report, used = generate_from_request(original_request, workspace, progress=progress)
        if report is not None:
            try:
                apply_outcome(ChunkStore(), used, success=True, strength=0.08)
            except Exception:
                pass
            return report
        if original is not None:
            return original(ask=ask, original_request=original_request, workspace=workspace, progress=progress)
        return None
    adaptive_execution._one_shot_browser_artifact = build
    adaptive_execution._code_memory_installed = True
