"""Public Sophyane Harness launcher with four explicit execution modes."""
from __future__ import annotations

import argparse
import os
import sys


MODES = (
    "deterministic",
    "internet",
    "local-llm",
    "cloud-llm",
)


def _apply_mode(mode: str) -> None:
    """Map the public harness mode to Sophyane's existing runtime policy."""
    normalized = str(mode or "").strip().lower()

    # Clear mutually exclusive public-mode flags first.
    for key in (
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        "SOPHYANE_SLI_CONTINUOUS",
        "SOPHYANE_TOPIC_LEARNING",
    ):
        os.environ.pop(key, None)

    if normalized == "deterministic":
        os.environ["SOPHYANE_SESSION_MODE"] = "race"
        os.environ["SOPHYANE_DISABLE_CLOUD_FALLBACK"] = "1"
        return

    if normalized == "internet":
        os.environ["SOPHYANE_SESSION_MODE"] = "sli_graph"
        os.environ["SOPHYANE_SLI_GRAPH"] = "1"
        os.environ["SOPHYANE_SLI_ONLY"] = "1"
        return

    if normalized == "local-llm":
        os.environ["SOPHYANE_SESSION_MODE"] = "local_llm"
        os.environ["SOPHYANE_LOCAL_ONLY"] = "1"
        os.environ["SOPHYANE_DISABLE_CLOUD_FALLBACK"] = "1"
        return

    if normalized == "cloud-llm":
        os.environ["SOPHYANE_SESSION_MODE"] = "cloud_llm"
        return

    raise ValueError(f"unsupported Sophyane Harness mode: {mode}")


def _interactive_mode() -> str:
    print("\nSophyane Harness")
    print("────────────────")
    print("  1. Deterministic — Sophyane execution/race without cloud rescue")
    print("  2. Internet — SLI Graph + internet, no local/cloud LLM")
    print("  3. Local LLM — llama.cpp / GGUF on-device model")
    print("  4. Cloud LLM — configured cloud provider")

    while True:
        answer = input("Select [1-4, default 1]: ").strip()
        if answer in {"", "1", "2", "3", "4"}:
            return {
                "": "deterministic",
                "1": "deterministic",
                "2": "internet",
                "3": "local-llm",
                "4": "cloud-llm",
            }[answer]
        print("Enter 1, 2, 3, or 4.")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-harness",
        description=(
            "Sophyane Harness — choose deterministic, internet, local LLM, "
            "or cloud LLM execution."
        ),
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=MODES,
        help="execution mode",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="launch the Sophyane browser UI after selecting the mode",
    )

    args, remainder = parser.parse_known_args()

    mode = args.mode
    if not mode:
        if sys.stdin.isatty():
            mode = _interactive_mode()
        else:
            mode = "deterministic"

    _apply_mode(mode)

    if args.web:
        from sophyane.web import main as run_web
        sys.argv = ["sophyane-web", *remainder]
        return int(run_web() or 0)

    from sophyane.cli_entry import main as run_cli
    sys.argv = ["sophyane", *remainder]
    return int(run_cli() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
