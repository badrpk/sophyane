from __future__ import annotations

from pathlib import Path

from sophyane.sli_capability_engine import evaluate_candidate


def _write_unrelated_cli(workspace: Path) -> None:
    """
    Produce a substantial, executable-looking artifact whose comments and
    dormant vocabulary resemble the requested capabilities while its actual
    CLI contract performs an unrelated task.

    The regression intentionally avoids depending on the historical
    release-builder artifact.  The invariant is generic:
    lexical/semantic vocabulary must not substitute for executable
    behavioral coherence.
    """
    workspace.mkdir(parents=True, exist_ok=True)

    source = r'''
from __future__ import annotations

import argparse
import subprocess
import socket


# Vocabulary deliberately resembling operational-agent requirements:
#
# monitor daemon logs stdout stderr tail
# diagnose memory out-of-memory port bind socket
# process supervision poll wait terminate kill
# safe command execution shell=False timeout check=True
# validation rules allow error handling
#
# None of those capabilities are exposed by the executable interface.


def unrelated_operation(name: str) -> str:
    # Keep the implementation non-trivial so artifact-size/source-presence
    # scoring cannot reject it for being a tiny placeholder.
    values = []
    for index in range(200):
        values.append(f"{name}:{index}")
    return "\n".join(values)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an unrelated catalog artifact."
    )
    parser.add_argument(
        "--catalog-name",
        required=True,
    )
    parser.add_argument(
        "--output",
        default="catalog.txt",
    )

    args = parser.parse_args()

    payload = unrelated_operation(args.catalog_name)

    with open(
        args.output,
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

    (workspace / "main.py").write_text(
        source,
        encoding="utf-8",
    )


def test_unrelated_executable_is_not_accepted_from_lexical_overlap(
    tmp_path: Path,
) -> None:
    request = (
        "Build a terminal-access agent with explicit safety guardrails "
        "to monitor long-running background processes and daemon crash "
        "logs, diagnose memory exhaustion and port-binding conflicts, "
        "and execute safe corrective shell commands."
    )

    workspace = tmp_path / "artifact"
    _write_unrelated_cli(workspace)

    result = evaluate_candidate(
        request,
        workspace,
        "Success: True",
        used=[],
        semantic_plan=None,
    )

    print()
    print("score =", result.score)
    print("accepted =", result.accepted)
    print("issues =", result.issues)

    assert result.accepted is False, (
        "An artifact with unrelated executable behavior was accepted "
        "because structural/lexical evidence was treated as behavioral "
        "coherence."
    )


def test_low_lexical_relevance_cannot_still_be_accepted(
    tmp_path: Path,
) -> None:
    """
    A low-relevance issue must have acceptance consequences rather than
    being informational only.
    """
    workspace = tmp_path / "artifact"
    workspace.mkdir(parents=True)

    (workspace / "main.py").write_text(
        '''
from __future__ import annotations

import argparse


def calculate_invoice_total(values):
    return sum(values)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare customer invoices."
    )
    parser.add_argument("--invoice", required=True)
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
        + ("\n# ordinary accounting implementation" * 100),
        encoding="utf-8",
    )

    request = (
        "Implement a daemon supervisor that continuously observes worker "
        "process health, reads crash logs, diagnoses resource exhaustion, "
        "checks network listener conflicts, and performs guarded recovery."
    )

    result = evaluate_candidate(
        request,
        workspace,
        "Success: True",
        used=[],
        semantic_plan=None,
    )

    print()
    print("score =", result.score)
    print("accepted =", result.accepted)
    print("issues =", result.issues)

    assert "low artifact relevance" in result.issues

    assert result.accepted is False, (
        "Low request-to-artifact relevance was reported but did not "
        "prevent acceptance."
    )
