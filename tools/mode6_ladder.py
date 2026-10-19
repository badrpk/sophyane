"""Small, causally-attributed Mode-6 capability ladder.

Repairs are accepted only when the provider succeeds, Sophyane source changes,
the challenge remains unchanged, and the verifier passes afterward.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from mode6_failure_supervisor import (
    FaultDomain,
    build_cloud_repair_request,
    causal_rsi_improvement_allowed,
    classify_failure,
)


class VerificationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    request: str
    verifier: Callable[[Any], Any]


def snapshot_subtree(prefix: str) -> dict[str, str]:
    root = Path(prefix)
    if not root.exists():
        return {}
    files = [root] if root.is_file() else sorted(root.rglob("*"))
    result: dict[str, str] = {}
    for path in files:
        if path.is_file():
            try:
                result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
    return result


def shell_command(command: str, request: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, shell=True, text=True, capture_output=True)


def run_cloud_repair(**kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="cloud repair unavailable")


def critical_repair_succeeded(result: subprocess.CompletedProcess[str]) -> bool:
    return int(getattr(result, "returncode", 1)) == 0


def append_journal(event: dict[str, Any]) -> None:
    path = Path(".sophyane-evolution") / "mode6-journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _reject(reason: str, level: Level, evidence: str) -> bool:
    append_journal({
        "event": "sophyane_improvement_rejected",
        "reason": reason,
        "level": level.number,
        "evidence": evidence,
    })
    return False


def execute_level(level: Level, command: str = "", dry_run: bool = False) -> bool:
    if dry_run:
        return False
    before = None
    try:
        before = level.verifier(None)
        return True
    except VerificationFailure as failure:
        evidence = str(failure)
    except Exception as failure:
        append_journal({"event": "controller_failure", "level": level.number, "evidence": str(failure)})
        return False

    source_before = snapshot_subtree("src/sophyane")
    challenge_before = snapshot_subtree("mode6_ladder_workspace")
    domain = classify_failure(
        verifier_kind="verification_failure",
        mode6_returncode=0,
        task_repairs=0,
    )
    repair = run_cloud_repair(
        request=build_cloud_repair_request(
            domain=domain,
            level_number=level.number,
            evidence=evidence,
        ),
        level=level,
        command=command,
    )
    if not critical_repair_succeeded(repair):
        return _reject("provider_failure", level, evidence)

    source_after = snapshot_subtree("src/sophyane")
    challenge_after = snapshot_subtree("mode6_ladder_workspace")
    if challenge_after != challenge_before:
        return _reject("challenge_mutated_during_repair", level, evidence)
    if source_after == source_before:
        return _reject("no_sophyane_source_delta", level, evidence)
    if not causal_rsi_improvement_allowed(
        provider_returncode=getattr(repair, "returncode", 1),
        sophyane_source_changed=source_after != source_before,
        challenge_changed_during_repair=challenge_after != challenge_before,
    ):
        return _reject("causal_attribution_failed", level, evidence)

    try:
        level.verifier(before)
    except Exception as failure:
        return _reject("verification_failed_after_repair", level, str(failure))
    append_journal({
        "event": "sophyane_improvement_verified",
        "level": level.number,
        "domain": domain.value,
    })
    return True
