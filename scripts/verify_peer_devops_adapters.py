#!/usr/bin/env python3
"""Verify local peer adapter wiring without modifying a production repository."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REPOSITORIES = ("veyron", "huobz", "rangoons", "shmry")


def _write_fixture(root: Path, repository: str) -> None:
    peer = root / repository
    peer.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "sophyane-ecosystem-v1",
        "component": repository,
        "role": "verification-fixture",
        "capabilities": ["status"],
        "peers": {"sophyane": "multi-option-harness"},
        "routing": {
            "policy": "request-peer-capability-when-local-capability-is-missing",
            "transport": ["local-process"],
            "fallback": "return-explicit-capability-unavailable",
        },
        "operations": {
            "status": {
                "argv": [
                    sys.executable,
                    "-c",
                    f"print({repository!r} + '-ready')",
                ],
                "timeout_seconds": 5,
                "max_output_bytes": 1024,
            }
        },
    }
    (peer / "ecosystem.json").write_text(json.dumps(payload))


def verify_peer_devops_adapters() -> dict[str, object]:
    # This deliberately uses isolated temporary roots. It proves registration
    # and invocation without running build/test commands in any real checkout.
    from sophyane.ecosystem_peer_runtime import register_local_peer_adapters
    from sophyane.peer_capability_adapter import invoke_peer_capability

    with tempfile.TemporaryDirectory(prefix="sophyane-peer-verify-") as raw:
        root = Path(raw)
        for repository in REPOSITORIES:
            _write_fixture(root, repository)
        registered = register_local_peer_adapters(roots=[root])
        results = {}
        for repository in REPOSITORIES:
            result = invoke_peer_capability(
                repository=repository,
                capability="status",
                objective="fixture verification",
                workspace=root / repository,
            )
            results[repository] = result.to_dict()
        return {
            "fixture_verification": {
                "ok": set(registered) >= set(REPOSITORIES)
                and all(item["ok"] for item in results.values()),
                "repositories": list(REPOSITORIES),
                "registered": list(registered),
                "results": results,
            }
        }


def main() -> int:
    report = verify_peer_devops_adapters()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["fixture_verification"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
