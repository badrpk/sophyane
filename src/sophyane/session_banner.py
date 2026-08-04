from __future__ import annotations
import os

def model_ready_label(model: str | None = None) -> str:
    if os.environ.get("SOPHYANE_SLI_ONLY") == "1" or os.environ.get("SOPHYANE_SESSION_MODE") == "sli_chunks":
        return "SLI chunks · Ready"
    label = (model or "").strip() or "model"
    return f"{label} · Ready"
