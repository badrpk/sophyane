from __future__ import annotations

import re
from pathlib import Path


_USE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
_PINNED_ACTION = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40}$"
)


def test_every_github_workflow_action_is_pinned_to_a_full_commit_sha():
    workflow_dir = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    uses = [value for path in sorted(workflow_dir.glob("*.yml"))
            for value in _USE.findall(path.read_text(encoding="utf-8"))]
    assert uses, "expected repository workflows to declare pinned actions"
    assert all(_PINNED_ACTION.fullmatch(value) for value in uses), [
        value for value in uses if not _PINNED_ACTION.fullmatch(value)
    ]
