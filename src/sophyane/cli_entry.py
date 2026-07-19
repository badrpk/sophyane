"""Public CLI entry point with explicit runtime identity."""
from __future__ import annotations

import os
import sys

from sophyane.config import load_config
from sophyane.version import __version__


def _runtime_identity() -> str:
    try:
        config = load_config()
    except Exception:
        config = {}

    local_edition = os.environ.get("SOPHYANE_EDITION", "").lower() == "local"
    configured_provider = str(config.get("provider") or "").strip()
    configured_model = str(config.get("model") or "").strip()

    if local_edition and configured_provider not in {"local_gguf", "ollama"}:
        provider = "local_gguf"
        model = "select-on-first-run"
    else:
        provider = configured_provider or ("local_gguf" if local_edition else "gemini")
        model = configured_model or (
            "select-on-first-run" if local_edition else "gemini-2.5-flash"
        )

    edition = "Local" if provider in {"local_gguf", "ollama"} or local_edition else "Frontier"
    return f"◆ Sophyane {edition} {__version__} | provider: {provider} | model: {model}"


def _user_start_tips() -> str:
    local_edition = os.environ.get("SOPHYANE_EDITION", "").lower() == "local"
    if local_edition:
        return (
            "Sophyane Local — private on-device inference\n"
            "  API key: not required\n"
            "  First run: choose Local GGUF to view the supported model catalog\n"
            "  Catalog: model source, download size, minimum RAM, and device fit\n"
            "  Backend: Hugging Face GGUF + llama.cpp from GitHub\n"
            "  Setup again: sophyane --setup\n"
            "  Status: sophyane --status | sophyane --doctor\n"
            "  Docs: https://github.com/badrpk/sophyane/blob/main/DOWNLOAD.md\n"
        )
    return (
        "Sophyane Frontier — hosted frontier LLMs\n"
        "  Default LLM: Google Gemini (gemini-2.5-flash)\n"
        "  Set key: export GEMINI_API_KEY=... or run sophyane --setup\n"
        "  CLI: sophyane --doctor | --capabilities | --boot | --audit\n"
        "  Docs: https://github.com/badrpk/sophyane\n"
    )


def main() -> int:
    print(_runtime_identity(), file=sys.stderr, flush=True)
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli

    return run_cli()
