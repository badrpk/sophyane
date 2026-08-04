
"""Generate via SLI chunk composition (no product hardcoding)."""
from __future__ import annotations
from pathlib import Path
from typing import Callable
from sophyane.code_memory.compose import compose_from_request
from sophyane.code_memory.store import ChunkStore

def generate_from_request(message: str, workspace: Path, *, store=None, top_k=12, min_score=0.01, progress=None):
    return compose_from_request(message, workspace, store=store, progress=progress)
