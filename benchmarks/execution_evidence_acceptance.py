#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from sophyane.execution_evidence import EvidenceVerifier, WorkspaceExecutor


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        executable = Path(sys.executable).name
        executor = WorkspaceExecutor(temp, allowed_commands={executable})
        executor.write_text("demo.py", "print('verified-execution')\n")
        command = executor.run([sys.executable, "demo.py"])
        ok, reasons = EvidenceVerifier().verify(
            executor.report,
            required_files=["demo.py"],
            required_commands=[executable],
        )
        result = {
            "passed": ok and command.stdout.strip() == "verified-execution",
            "verification_reasons": reasons,
            "execution": executor.report.to_dict(),
        }

    output = Path("benchmark-results/execution-evidence")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# Sophyane execution evidence acceptance",
        "",
        f"- Overall: **{'PASS' if result['passed'] else 'FAIL'}**",
        f"- Files evidenced: **{len(result['execution']['files'])}**",
        f"- Commands evidenced: **{len(result['execution']['commands'])}**",
        f"- Exit code: **{command.exit_code}**",
        f"- SHA-256 recorded: **{bool(result['execution']['files'][0]['sha256'])}**",
    ]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
