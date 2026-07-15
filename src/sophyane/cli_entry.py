"""Public CLI entry point with explicit runtime identity (Grok-style)."""
from __future__ import annotations

import sys

from sophyane.config import load_config
from sophyane.version import __version__


def _runtime_identity() -> str:
    try:
        config = load_config()
    except Exception:
        config = {}
    provider = str(config.get("provider") or "not configured")
    model = str(config.get("model") or "not configured")
    return f"◆ Sophyane {__version__} | provider: {provider} | model: {model}"


def _user_start_tips() -> str:
    return (
        "Start guide for users:\n"
        "  Web: open /start.html on the cloud portal (sophyane --cloud-serve → :8780)\n"
        "  Auth: email OTP from badrpk@gmail.com — signup once, then login with OTP\n"
        "  API:  POST /api/v1/auth/request-otp → verify-otp → sph_ key → POST /api/v1/chat\n"
        "  CLI:  sophyane --doctor | --capabilities | --boot | --audit\n"
        "  Docs: https://github.com/badrpk/sophyane  ·  install.sh always pulls latest release\n"
    )


def main() -> int:
    # stderr keeps --agent-json stdout valid while making the LLM visible first.
    print(_runtime_identity(), file=sys.stderr, flush=True)
    # Interactive / bare start: show essentials so users see them immediately
    if len(sys.argv) <= 1:
        print(_user_start_tips(), file=sys.stderr, flush=True)
    from sophyane.v13_cli import main as run_cli

    return run_cli()
