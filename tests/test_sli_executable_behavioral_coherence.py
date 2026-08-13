from __future__ import annotations

from pathlib import Path

from sophyane.sli_capability_engine import evaluate_candidate


REQUEST = (
    "Provide a terminal-access agent with explicit safety guardrails "
    "to monitor long-running background processes or daemon crash logs, "
    "dynamically diagnose out-of-memory or port-binding conflicts, "
    "and execute safe corrective shell scripts."
)


def _write_behaviorally_incoherent_artifact(
    workspace: Path,
) -> None:
    workspace.mkdir(parents=True, exist_ok=True)

    source = r'''
from __future__ import annotations

import argparse
import socket
import subprocess


# These helpers deliberately contain genuine-looking implementation
# vocabulary relevant to the requested operational capabilities.
#
# They are not the executable behavior exposed by this program.


def read_daemon_crash_log(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def diagnose_out_of_memory(log_text):
    return (
        "out of memory" in log_text.lower()
        or "oom" in log_text.lower()
    )


def diagnose_port_binding(host, port):
    sock = socket.socket()
    try:
        sock.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def monitor_process(process):
    return process.poll()


def guarded_recovery(command):
    allowed = {"status", "restart"}
    if command not in allowed:
        raise ValueError("command not allowed")

    return subprocess.run(
        ["echo", command],
        shell=False,
        check=True,
        timeout=5,
        capture_output=True,
        text=True,
    )


# Actual executable contract is deliberately unrelated.


def calculate_invoice_total(values):
    return sum(values)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Prepare customer invoices."
    )
    parser.add_argument(
        "--invoice",
        required=True,
        help="Invoice identifier",
    )
    parser.add_argument(
        "--amount",
        action="append",
        type=float,
        default=[],
    )

    args = parser.parse_args(argv)

    total = calculate_invoice_total(args.amount)

    print(
        f"invoice={args.invoice} total={total:.2f}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

    # Make this substantial enough that source size / implementation
    # volume cannot itself explain rejection.
    source += (
        "\n# daemon process crash log memory port "
        "monitor recovery safety validation command"
        * 120
    )

    (workspace / "main.py").write_text(
        source,
        encoding="utf-8",
    )


def test_relevant_helpers_cannot_launder_unrelated_entry_point(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "artifact"

    _write_behaviorally_incoherent_artifact(
        workspace,
    )

    result = evaluate_candidate(
        REQUEST,
        workspace,
        "Success: True",
        used=[],
        semantic_plan=None,
    )

    print()
    print("score =", result.score)
    print("accepted =", result.accepted)
    print("issues =", result.issues)

    assert "low artifact relevance" not in result.issues, (
        "Fixture did not cross the V1 lexical relevance gate; "
        "this would only retest the previous regression."
    )

    assert result.accepted is False, (
        "A lexically relevant implementation with unrelated "
        "executable behavior was accepted. Relevant dormant/helper "
        "code must not establish executable behavioral coherence."
    )


def test_fixture_is_valid_python(tmp_path: Path) -> None:
    workspace = tmp_path / "artifact"

    _write_behaviorally_incoherent_artifact(
        workspace,
    )

    path = workspace / "main.py"
    source = path.read_text(encoding="utf-8")

    compile(
        source,
        str(path),
        "exec",
    )


def test_behaviorally_aligned_entry_point_remains_acceptable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "aligned"
    workspace.mkdir(parents=True)

    source = r'''
from __future__ import annotations

import argparse
import subprocess


def monitor_process(pid):
    return pid


def read_crash_log(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def diagnose_resource_exhaustion(text):
    return "out of memory" in text.lower()


def guarded_recovery(command):
    return subprocess.run(
        command,
        shell=False,
        check=True,
        timeout=5,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Monitor background processes and daemon crash logs, "
            "diagnose memory and port failures, and execute guarded "
            "corrective commands."
        )
    )

    parser.add_argument(
        "--process",
        help="Process identifier to monitor",
    )

    parser.add_argument(
        "--log",
        help="Daemon crash log to inspect",
    )

    parser.add_argument(
        "--recover",
        help="Safe corrective command to execute",
    )

    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

    # Keep artifact substantial enough to exercise ordinary general scoring.
    source += (
        "\n# monitor process daemon crash log memory port "
        "diagnose recovery corrective command safety"
        * 100
    )

    (workspace / "main.py").write_text(
        source,
        encoding="utf-8",
    )

    result = evaluate_candidate(
        REQUEST,
        workspace,
        "Success: True",
        used=[],
        semantic_plan=None,
    )

    print()
    print("aligned score =", result.score)
    print("aligned accepted =", result.accepted)
    print("aligned issues =", result.issues)

    assert result.accepted is True


def test_behaviorally_aligned_entry_point_remains_acceptable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "aligned"
    workspace.mkdir(parents=True)

    source = r'''
from __future__ import annotations

import argparse
import subprocess


def monitor_process(pid):
    return pid


def read_crash_log(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def diagnose_resource_exhaustion(text):
    return "out of memory" in text.lower()


def guarded_recovery(command):
    return subprocess.run(
        command,
        shell=False,
        check=True,
        timeout=5,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Monitor background processes and daemon crash logs, "
            "diagnose memory and port failures, and execute guarded "
            "corrective commands."
        )
    )

    parser.add_argument(
        "--process",
        help="Process identifier to monitor",
    )

    parser.add_argument(
        "--log",
        help="Daemon crash log to inspect",
    )

    parser.add_argument(
        "--recover",
        help="Safe corrective command to execute",
    )

    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

    # Keep artifact substantial enough to exercise ordinary general scoring.
    source += (
        "\n# monitor process daemon crash log memory port "
        "diagnose recovery corrective command safety"
        * 100
    )

    (workspace / "main.py").write_text(
        source,
        encoding="utf-8",
    )

    result = evaluate_candidate(
        REQUEST,
        workspace,
        "Success: True",
        used=[],
        semantic_plan=None,
    )

    print()
    print("aligned score =", result.score)
    print("aligned accepted =", result.accepted)
    print("aligned issues =", result.issues)

    assert result.accepted is True
