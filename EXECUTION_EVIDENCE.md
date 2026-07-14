# Evidence-backed execution

Sophyane v13 includes workspace-confined execution primitives that produce objective evidence instead of trusting a model's narrative.

## Filesystem evidence

`WorkspaceExecutor.write_text()` resolves every path against a configured workspace, blocks path traversal, writes the file, and records:

- absolute path;
- byte size;
- SHA-256 digest.

`verify_file()` can re-read an existing artifact and record its current digest.

## Shell evidence

`WorkspaceExecutor.run()` accepts an argument list rather than a shell string. It permits only configured executable names and records:

- exact argv;
- working directory;
- start and finish timestamps;
- exit code;
- timeout status;
- stdout and stderr.

Commands execute without `shell=True`, reducing interpretation and injection risk. The default allowlist contains Python, pytest, Ruff, mypy, pyright, and Git. Applications should narrow this list further when possible.

## Verification rule

`EvidenceVerifier` rejects success when:

- required file evidence is missing;
- required command evidence is missing;
- no filesystem evidence exists;
- no shell evidence exists;
- a command times out;
- any command exits nonzero.

A worker statement such as “tests passed” therefore cannot satisfy the verifier by itself.

## Example

```python
from pathlib import Path
import sys

from sophyane.execution_evidence import EvidenceVerifier, WorkspaceExecutor

workspace = WorkspaceExecutor(
    "./harness_tests/example",
    allowed_commands={Path(sys.executable).name},
)
workspace.write_text("answer.py", "print(42)\n")
workspace.run([sys.executable, "answer.py"])

verified, reasons = EvidenceVerifier().verify(
    workspace.report,
    required_files=["answer.py"],
    required_commands=[Path(sys.executable).name],
)
assert verified, reasons
workspace.report.write_json("./harness_tests/example/evidence.json")
```

## Acceptance

```bash
python -m pytest tests/test_execution_evidence.py
python benchmarks/execution_evidence_acceptance.py
cat benchmark-results/execution-evidence/REPORT.md
```

This module supplies the trusted execution boundary. Multi-agent workers must call it and the final reviewer must consume its structured report before an end-to-end CLI run can claim that files were created or checks passed.
