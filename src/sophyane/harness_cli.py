"""Public Sophyane Harness launcher with five original execution modes."""
from __future__ import annotations

import argparse
import os
import sys


MODES = (
    "auto",
    "internet",
    "local-llm",
    "cloud-llm",
    "learning",
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

    if normalized == "auto":
        os.environ["SOPHYANE_SESSION_MODE"] = "race"
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

    if normalized == "learning":
        os.environ["SOPHYANE_SESSION_MODE"] = "sli_graph"
        os.environ["SOPHYANE_SLI_GRAPH"] = "1"
        os.environ["SOPHYANE_SLI_ONLY"] = "1"
        os.environ["SOPHYANE_SLI_CONTINUOUS"] = "1"
        os.environ["SOPHYANE_TOPIC_LEARNING"] = "1"
        return

    raise ValueError(f"unsupported Sophyane Harness mode: {mode}")


def _interactive_mode() -> str:
    print("\nSophyane Harness")
    print("────────────────")
    print("  1. Sophyane Auto — intelligently decide between available capabilities")
    print("  2. Internet — SLI Graph + memory + internet, no LLM")
    print("  3. Local LLM — llama.cpp / GGUF on-device model")
    print("  4. Cloud LLM — configured cloud provider")
    print("  5. Sophyane Learning — acquire + embed continuously until Ctrl+C")

    while True:
        answer = input("Select [1-5, default 1]: ").strip()
        if answer in {"", "1", "2", "3", "4", "5"}:
            return {
                "": "auto",
                "1": "auto",
                "2": "internet",
                "3": "local-llm",
                "4": "cloud-llm",
                "5": "learning",
            }[answer]
        print("Enter 1, 2, 3, 4, or 5.")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sophyane-harness",
        description=(
            "Sophyane Harness — choose Auto, Internet, Local LLM, Cloud LLM, "
            "or continuous Learning mode."
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
            mode = "auto"

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
