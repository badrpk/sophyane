#!/usr/bin/env python3
"""Trusted dispatcher CLI for GitHub-hosted SSEE qualification."""
from __future__ import annotations

import argparse
import json
import os
import sys

from sophyane.ssee.remote.github_hosted import (
    GitHubHostedQualificationClient,
    GitHubSSEEError,
    HostedQualificationError,
    QualificationRequest,
)


def _client(args):
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise HostedQualificationError("set GH_TOKEN in the trusted dispatcher environment")
    return GitHubHostedQualificationClient(args.owner, args.repo, token)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="badrpk")
    parser.add_argument("--repo", default="sophyane")
    commands = parser.add_subparsers(dest="command", required=True)
    dispatch = commands.add_parser("dispatch")
    dispatch.add_argument("--candidate-sha", required=True)
    dispatch.add_argument("--workflow-sha", required=True)
    dispatch.add_argument("--fixture", choices=("candidate", "pass", "fail", "timeout", "network"), default="candidate")
    for command in ("status", "cancel", "evidence"):
        item = commands.add_parser(command)
        item.add_argument("--request-id", required=True)
        item.add_argument("--candidate-sha", required=True)
        item.add_argument("--workflow-sha", required=True)
    args = parser.parse_args(argv)
    try:
        client = _client(args)
        if args.command == "dispatch":
            result = client.dispatch(args.candidate_sha,
                                     expected_workflow_sha=args.workflow_sha,
                                     fixture=args.fixture)
        else:
            request = QualificationRequest(args.candidate_sha, args.request_id)
            request_data = {"request_id": request.request_id,
                            "candidate_sha": request.candidate_sha,
                            "workflow_sha": args.workflow_sha}
            if args.command == "cancel":
                result = client.cancel(request_data)
            else:
                completed = client.status(request_data)
                result = (completed if args.command == "status"
                          else client.retrieve_evidence(request_data, completed))
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (GitHubSSEEError, ValueError, TimeoutError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)},
                         sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
