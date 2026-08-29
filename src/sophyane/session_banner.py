from __future__ import annotations
import os

def model_ready_label(model: str | None = None) -> str:
    if os.environ.get("SOPHYANE_SLI_ONLY") == "1" or os.environ.get("SOPHYANE_SESSION_MODE") == "sli_chunks":
        return ("SLI Graph · Ready" if os.environ.get("SOPHYANE_SLI_GRAPH") == "1" else "SLI chunks · Ready")
    # Explicit startup provider/model selection is session-scoped
    # authority. Never display a stale persisted model when the current
    # process selected another provider such as NIFDU Browser.
    session_model = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODEL"
        )
        or ""
    ).strip()

    label = (
        session_model
        or (model or "").strip()
        or "model"
    )

    return f"{label} · Ready"
