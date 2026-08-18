"""Sophyane v16 CLI: repository-aware coding execution by default."""
from __future__ import annotations
import re

import argparse
import json
import os
import time
from pathlib import Path

from sophyane.agent import SophyaneAgent
from sophyane.autonomy import AUTONOMOUS_WORKER_POLICY
from sophyane.config import ensure_directories
from sophyane.diagnostics import run_diagnostics
from sophyane.live_coding_doer import LiveProgressReporter
from sophyane.logging_config import configure_logging
from sophyane.main import (
    create_provider,
    handle_internal_command,
    interactive,
    list_providers,
    load_runtime_config,
    show_status,
)
from sophyane.memory import MemoryStore
from sophyane.multiagent import MultiAgentRuntime, MultiAgentStore
from sophyane.setup_wizard import run_setup_wizard
from sophyane.strict_interactive_doer import StrictInteractiveCodingDoerRuntime
from sophyane.structured_output import (
    StructuredOutputError,
    render_strict_json,
    requests_strict_json,
)
from sophyane.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane",
        description=(
            "Sophyane v16 repository-aware coding agent with semantic indexing, "
            "precise patches, batched tools, self-repair and deterministic verification."
        ),
    )
    parser.add_argument("prompt", nargs="*", help="prompt to process")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--providers", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument(
        "--platform",
        action="store_true",
        help="probe OS/hardware/equipment class (Windows/macOS/Linux/Android/edge)",
    )
    parser.add_argument(
        "--edge-health",
        action="store_true",
        help="print edge/IoT health JSON for constrained chips and gateways",
    )
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="print hardware vendor compatibility report (NVIDIA/Intel/AMD/…)",
    )
    parser.add_argument(
        "--hardware-json",
        action="store_true",
        help="print hardware compatibility report as JSON",
    )
    parser.add_argument(
        "--hardware-api",
        action="store_true",
        help="serve multi-language Hardware API (Python/C++/JS clients)",
    )
    parser.add_argument(
        "--hardware-host",
        default="127.0.0.1",
        help="bind host for --hardware-api (default 127.0.0.1)",
    )
    parser.add_argument(
        "--hardware-port",
        type=int,
        default=8770,
        help="bind port for --hardware-api (default 8770)",
    )
    parser.add_argument(
        "--mesh-api",
        action="store_true",
        help="serve Sophyane Mesh API",
    )
    parser.add_argument(
        "--mesh-host",
        default="127.0.0.1",
        help="bind host for --mesh-api",
    )
    parser.add_argument(
        "--mesh-port",
        type=int,
        default=8777,
        help="bind port for --mesh-api",
    )
    parser.add_argument(
        "--mesh-status",
        action="store_true",
        help="print mesh status JSON",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--race", action="store_true")
    parser.add_argument("--race-fast", action="store_true")
    parser.add_argument("--race-workers", type=int, default=3)
    parser.add_argument("--race-timeout", type=int, default=180)
    parser.add_argument("--race-json", action="store_true")
    parser.add_argument("--ask")
    parser.add_argument("--exam-tough100", action="store_true")
    parser.add_argument("--exam-mode", default="hybrid")
    parser.add_argument("--exam-limit", type=int, default=100)
    parser.add_argument("--expert-only", action="store_true")
    parser.add_argument("--skill")
    parser.add_argument("--skill-prompt")
    parser.add_argument("--cloud-portal", action="store_true")
    parser.add_argument("--cloud-host", default="127.0.0.1")
    parser.add_argument("--cloud-port", type=int, default=8788)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


# NOTE: file body intentionally omitted in this reconstruction is unacceptable.
