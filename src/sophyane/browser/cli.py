"""CLI commands for Sophyane Browser CDP control."""

from __future__ import annotations

import argparse
import json
import os
from typing import Sequence

from sophyane.browser.cdp import CDPEndpoint, CDPError, list_targets, target_summary
from sophyane.browser.launcher import launch_sophyane_browser


def build_browser_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sophyane browser")
    sub = parser.add_subparsers(dest="browser_command", required=True)

    start = sub.add_parser("start", help="launch Sophyane Browser")
    start.add_argument("--cdp", action="store_true", help="enable loopback Chrome DevTools Protocol")
    start.add_argument("--json", action="store_true", help="machine-readable output")

    status = sub.add_parser("status", help="show browser/CDP status")
    status.add_argument("--host", default="127.0.0.1")
    status.add_argument("--port", type=int, default=0)
    status.add_argument("--json", action="store_true")

    targets = sub.add_parser("targets", help="list CDP targets")
    targets.add_argument("--host", default="127.0.0.1")
    targets.add_argument("--port", type=int, default=0)
    targets.add_argument("--json", action="store_true")

    open_cmd = sub.add_parser("open", help="open a URL in a CDP-enabled browser")
    open_cmd.add_argument("url")
    open_cmd.add_argument("--json", action="store_true")

    return parser


def _env_port() -> int:
    value = os.environ.get("SOPHYANE_CDP_PORT", "").strip()
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _endpoint(host: str, port: int) -> CDPEndpoint:
    actual_port = int(port or _env_port())
    if actual_port <= 0:
        raise CDPError(
            "CDP port is unknown. Start with 'sophyane browser start --cdp' "
            "or set SOPHYANE_CDP_PORT."
        )
    return CDPEndpoint(host=host, port=actual_port)


def _print(payload: object, *, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_browser_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.browser_command == "start":
            result = launch_sophyane_browser(
                open_home=True,
                start_apis=True,
                enable_cdp=bool(args.cdp),
            )
            _print(result, as_json=True)
            return 0 if result.get("ok") else 1

        if args.browser_command == "status":
            result = target_summary(_endpoint(str(args.host), int(args.port)))
            _print(result, as_json=True)
            return 0

        if args.browser_command == "targets":
            endpoint = _endpoint(str(args.host), int(args.port))
            result = {
                "ok": True,
                "endpoint": endpoint.base_url,
                "targets": list_targets(endpoint),
            }
            _print(result, as_json=True)
            return 0

        if args.browser_command == "open":
            result = launch_sophyane_browser(
                open_home=False,
                start_apis=False,
                enable_cdp=True,
                initial_url=str(args.url),
            )
            _print(result, as_json=True)
            return 0 if result.get("ok") else 1

    except CDPError as error:
        _print({"ok": False, "error": str(error)}, as_json=True)
        return 2

    parser.error("unknown browser command")
    return 2
