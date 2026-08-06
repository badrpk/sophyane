import json
from pathlib import Path

import pytest

from sophyane.evolution.candidate_evolution import (
    CandidateEvolver,
    _changed_lines,
    _diff_paths,
)
from sophyane.evolution.models import (
    PatchProposal,
)


def _proposal(
    patch: str,
    *,
    component: str = "filesystem",
) -> PatchProposal:
    return PatchProposal(
        component=component,
        rationale="Reusable fix",
        patch=patch,
        tests=[],
        confidence=0.9,
        allowed_paths=[],
    )


def test_diff_path_extraction() -> None:
    patch = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-old
+new
"""

    assert _diff_paths(patch) == [
        "src/a.py",
    ]
    assert _changed_lines(patch) == 2


def test_one_source_and_one_test_are_allowed(
    tmp_path: Path,
) -> None:
    evolver = CandidateEvolver(
        tmp_path
    )

    proposal = _proposal(
        """diff --git a/src/sophyane/capability_executors.py b/src/sophyane/capability_executors.py
--- a/src/sophyane/capability_executors.py
+++ b/src/sophyane/capability_executors.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_filesystem_regression.py b/tests/test_filesystem_regression.py
new file mode 100644
--- /dev/null
+++ b/tests/test_filesystem_regression.py
@@ -0,0 +1 @@
+def test_regression(): assert True
"""
    )

    evolver.validate_proposal(
        proposal
    )


def test_two_source_files_are_rejected(
    tmp_path: Path,
) -> None:
    evolver = CandidateEvolver(
        tmp_path
    )

    proposal = _proposal(
        """diff --git a/src/sophyane/capability_executors.py b/src/sophyane/capability_executors.py
--- a/src/sophyane/capability_executors.py
+++ b/src/sophyane/capability_executors.py
@@ -1 +1 @@
-old
+new
diff --git a/src/sophyane/execution_runtime.py b/src/sophyane/execution_runtime.py
--- a/src/sophyane/execution_runtime.py
+++ b/src/sophyane/execution_runtime.py
@@ -1 +1 @@
-old
+new
"""
    )

    with pytest.raises(
        ValueError,
        match="exactly one",
    ):
        evolver.validate_proposal(
            proposal
        )


def test_cross_component_source_is_rejected(
    tmp_path: Path,
) -> None:
    evolver = CandidateEvolver(
        tmp_path
    )

    proposal = _proposal(
        """diff --git a/src/sophyane/semantic_intent_router.py b/src/sophyane/semantic_intent_router.py
--- a/src/sophyane/semantic_intent_router.py
+++ b/src/sophyane/semantic_intent_router.py
@@ -1 +1 @@
-old
+new
"""
    )

    with pytest.raises(
        ValueError,
        match="outside component",
    ):
        evolver.validate_proposal(
            proposal
        )


def test_skipped_test_is_rejected(
    tmp_path: Path,
) -> None:
    evolver = CandidateEvolver(
        tmp_path
    )

    proposal = _proposal(
        """diff --git a/src/sophyane/capability_executors.py b/src/sophyane/capability_executors.py
--- a/src/sophyane/capability_executors.py
+++ b/src/sophyane/capability_executors.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_filesystem_regression.py b/tests/test_filesystem_regression.py
new file mode 100644
--- /dev/null
+++ b/tests/test_filesystem_regression.py
@@ -0,0 +1,2 @@
+import pytest
+@pytest.mark.skip
"""
    )

    with pytest.raises(
        ValueError,
        match="Forbidden",
    ):
        evolver.validate_proposal(
            proposal
        )


def test_candidate_payload_accepts_valid_json() -> None:
    from sophyane.evolution.candidate_evolution import _candidate_payload

    patch = (
        "diff --git a/src/sophyane/capability_executors.py "
        "b/src/sophyane/capability_executors.py\n"
        "--- a/src/sophyane/capability_executors.py\n"
        "+++ b/src/sophyane/capability_executors.py\n"
        "@@ -1 +1 @@\n-old\n+new"
    )

    value = json.dumps(
        {
            "component": "python",
            "rationale": "Reusable execution fix",
            "patch": patch,
            "tests": [],
            "confidence": 0.9,
        }
    )

    payload = _candidate_payload(value, component="python")

    assert payload["component"] == "python"
    assert payload["patch"].startswith("diff --git ")


def test_candidate_payload_recovers_fenced_diff() -> None:
    from sophyane.evolution.candidate_evolution import _candidate_payload

    value = (
        "Reusable patch follows.\n\n"
        "```diff\n"
        "diff --git a/src/sophyane/capability_executors.py "
        "b/src/sophyane/capability_executors.py\n"
        "--- a/src/sophyane/capability_executors.py\n"
        "+++ b/src/sophyane/capability_executors.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/tests/test_python_execution_regression.py "
        "b/tests/test_python_execution_regression.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/tests/test_python_execution_regression.py\n"
        "@@ -0,0 +1 @@\n"
        "+def test_regression(): assert True\n"
        "```\n"
    )

    payload = _candidate_payload(value, component="python")

    assert payload["patch"].startswith("diff --git ")
    assert payload["tests"] == [
        "tests/test_python_execution_regression.py"
    ]
    assert payload["response_format_recovered"] is True


def test_candidate_payload_rejects_explanation_only() -> None:
    from sophyane.evolution.candidate_evolution import _candidate_payload

    with pytest.raises(ValueError, match="neither valid JSON"):
        _candidate_payload(
            "I recommend improving the executor.",
            component="python",
        )



def test_valid_patch_passes_pre_worktree_check(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )

    source = (
        tmp_path
        / "src/sophyane/capability_executors.py"
    )
    source.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    source.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    evolver = CandidateEvolver(tmp_path)

    patch = """diff --git a/src/sophyane/capability_executors.py b/src/sophyane/capability_executors.py
--- a/src/sophyane/capability_executors.py
+++ b/src/sophyane/capability_executors.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    valid, error = evolver._git_apply_check(patch)

    assert valid is True
    assert (
        error == ""
        or "checking patch" in error.casefold()
    )


def test_corrupt_patch_fails_before_worktree_creation(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    source = (
        tmp_path
        / "src/sophyane/capability_executors.py"
    )
    source.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    source.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    evolver = CandidateEvolver(tmp_path)

    corrupt = """diff --git a/src/sophyane/capability_executors.py b/src/sophyane/capability_executors.py
--- a/src/sophyane/capability_executors.py
+++ b/src/sophyane/capability_executors.py
@@ -1,5 +1,7 @@
-value = 1
+value = 2
"""

    valid, error = evolver._git_apply_check(corrupt)

    assert valid is False
    assert "corrupt patch" in error.casefold()
    assert not any(
        evolver.worktrees.iterdir()
    )


def test_json_patch_field_unwraps_fenced_diff_without_git_header() -> None:
    import json

    from sophyane.evolution.candidate_evolution import (
        _candidate_payload,
    )

    response = json.dumps(
        {
            "component": "python",
            "rationale": "Run requested tests.",
            "patch": (
                "```diff\n"
                "--- a/src/sophyane/local_coding_capability.py\n"
                "+++ b/src/sophyane/local_coding_capability.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "```"
            ),
            "tests": [],
            "confidence": 0.9,
        }
    )

    payload = _candidate_payload(
        response,
        component="python",
    )

    assert payload["patch"].startswith(
        "diff --git "
        "a/src/sophyane/local_coding_capability.py "
        "b/src/sophyane/local_coding_capability.py"
    )
    assert "```" not in payload["patch"]


def test_normalise_patch_preserves_existing_git_diff() -> None:
    from sophyane.evolution.candidate_evolution import (
        _normalise_patch_text,
    )

    patch = (
        "diff --git a/src/example.py b/src/example.py\n"
        "--- a/src/example.py\n"
        "+++ b/src/example.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    assert _normalise_patch_text(patch) == patch.strip()


def test_normalized_patch_uses_physical_newlines() -> None:
    import json

    from sophyane.evolution.candidate_evolution import (
        _candidate_payload,
        _diff_paths,
    )

    response = json.dumps(
        {
            "component": "python",
            "rationale": "Test patch normalization.",
            "patch": (
                "```diff\n"
                "--- a/src/sophyane/local_coding_capability.py\n"
                "+++ b/src/sophyane/local_coding_capability.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "```"
            ),
            "tests": [],
            "confidence": 0.9,
        }
    )

    payload = _candidate_payload(
        response,
        component="python",
    )

    patch = payload["patch"]

    assert "\\n" not in patch
    assert len(patch.splitlines()) == 6
    assert _diff_paths(patch) == [
        "src/sophyane/local_coding_capability.py"
    ]



def test_rejects_placeholder_index_and_benchmark_hardcoding() -> None:
    from sophyane.evolution.candidate_evolution import (
        _validate_unified_diff_structure,
    )

    patch = """diff --git a/src/sophyane/local_coding_capability.py b/src/sophyane/local_coding_capability.py
index 1234567..89abcdef 100644
--- a/src/sophyane/local_coding_capability.py
+++ b/src/sophyane/local_coding_capability.py
@@ -1,3 +1,10 @@
+def add(a, b):
+    return a + b
+
+def test_add():
+    assert add(20, 22) == 42
+
+if __name__ == '__main__':
+    test_add()
"""

    errors = _validate_unified_diff_structure(
        patch
    )

    assert any(
        "placeholder Git index" in item
        for item in errors
    )
    assert any(
        "benchmark literal" in item
        for item in errors
    )
    assert any(
        "old-line count mismatch" in item
        for item in errors
    )


def test_accepts_structurally_valid_general_patch() -> None:
    from sophyane.evolution.candidate_evolution import (
        _validate_unified_diff_structure,
    )

    patch = """diff --git a/src/sophyane/example.py b/src/sophyane/example.py
--- a/src/sophyane/example.py
+++ b/src/sophyane/example.py
@@ -1,2 +1,3 @@
 def execute(request):
+    verify_effects(request)
     return True
"""

    assert (
        _validate_unified_diff_structure(
            patch
        )
        == []
    )
