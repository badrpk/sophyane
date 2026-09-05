"""Native + combined worker chat surfaces (Sophyane policy only)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _norm(message: str) -> str:
    return " ".join(str(message or "").lower().split())


def try_native_status_reply(message: str) -> str | None:
    t = _norm(message)
    keys = (
        "native status",
        "nifdu available",
        "neuron available",
        "native backends",
        "native workers",
        "is nifdu installed",
        "is neuron installed",
    )
    if not any(k in t for k in keys):
        return None
    from sophyane.native_backends import status_text
    return status_text()


def try_combined_workers_reply(message: str) -> str | None:
    """Prefer native combined path; may auto-fetch binaries."""
    try:
        from sophyane.collaborative_workers import try_combined_reply
    except Exception:
        return None
    return try_combined_reply(message)


def try_nifdu_build_reply(message: str) -> str | None:
    """Run NIFDU's product builder only for an explicit user request."""
    text = str(message or "").strip()
    normalized = _norm(text)
    if normalized == "nifdu build":
        return "Please provide a product request for NIFDU."
    prefixes = ("nifdu build ", "use nifdu to build ", "build with nifdu ")
    prefix = next((p for p in prefixes if normalized.startswith(p)), None)
    if prefix is None:
        return None
    request = text[len(prefix):].strip()
    if not request:
        return "Please provide a product request for NIFDU."
    try:
        from sophyane.native_backends import probe_nifdu
        binary = os.environ.get("SOPHYANE_NIFDU_BUILDER_BIN") or probe_nifdu().path
        if binary:
            wrapper = Path(binary)
            sibling = wrapper.with_name("nifdu-bin")
            if wrapper.name == "nifdu" and sibling.is_file():
                binary = str(sibling)
        if not binary:
            return "NIFDU builder is unavailable on this device."
        build_env = os.environ.copy()
        selected_provider = (
            build_env.get("SOPHYANE_NIFDU_PROVIDER")
            or ({
                "nifdu_llm": "browser_chatgpt",
                "codex_cli": "codex_cli",
                "agy": "browser_chatgpt",
            }.get(build_env.get("SOPHYANE_SESSION_MODE", ""), ""))
        )
        if selected_provider:
            build_env["NIFDU_BUILDER_PROVIDER"] = selected_provider
            build_env["NIFDU_JUDGE_PROVIDER"] = selected_provider
        result = subprocess.run(
            [binary, "build", request], capture_output=True, text=True,
            timeout=float(os.environ.get("SOPHYANE_NIFDU_BUILD_TIMEOUT", "900")),
            env=build_env,
            check=False,
        )
    except Exception as exc:
        return f"NIFDU builder unavailable: {exc}"
    output = "\n".join(
        part.strip() for part in (result.stdout or "", result.stderr or "") if part.strip()
    )
    if result.returncode != 0:
        return f"NIFDU build failed (exit {result.returncode}).\n{output}".strip()
    return output or "NIFDU build completed."


def try_any_native_reply(message: str) -> str | None:
    return (
        try_native_status_reply(message)
        or try_nifdu_build_reply(message)
        or try_combined_workers_reply(message)
    )
