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


def test_local_candidate_policy_is_micro_patch_sized() -> None:
    import inspect

    import sophyane.evolution.candidate_evolution as module
    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )

    assert module.MAX_CHANGED_LINES == 20

    source = inspect.getsource(
        CandidateEvolver.generate_proposal
    )

    assert "Produce one micro-patch only" in source
    assert "no more than 20 total added/removed lines" in source
    assert "one function or one adjacent code block" in source


def test_micro_edit_constructs_valid_git_patch(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.candidate_evolution import (
        _diff_paths,
        _micro_edit_to_patch,
        _validate_unified_diff_structure,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def execute(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    patch = _micro_edit_to_patch(
        repo=tmp_path,
        component="python",
        payload={
            "file": (
                "src/sophyane/"
                "local_coding_capability.py"
            ),
            "find": (
                "def execute(value):\n"
                "    return value\n"
            ),
            "replace": (
                "def execute(value):\n"
                "    if value is None:\n"
                "        return False\n"
                "    return value\n"
            ),
        },
    )

    assert patch.startswith(
        "diff --git "
    )

    assert _diff_paths(patch) == [
        (
            "src/sophyane/"
            "local_coding_capability.py"
        )
    ]

    assert (
        _validate_unified_diff_structure(
            patch
        )
        == []
    )


def test_micro_edit_requires_unique_exact_match(
    tmp_path: Path,
) -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _micro_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "value = 1\n"
        "value = 1\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="must occur once",
    ):
        _micro_edit_to_patch(
            repo=tmp_path,
            component="python",
            payload={
                "file": (
                    "src/sophyane/"
                    "local_coding_capability.py"
                ),
                "find": "value = 1\n",
                "replace": "value = 2\n",
            },
        )


def test_micro_edit_rejects_benchmark_literal(
    tmp_path: Path,
) -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _micro_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def check():\n"
        "    return True\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="benchmark literal",
    ):
        _micro_edit_to_patch(
            repo=tmp_path,
            component="python",
            payload={
                "file": (
                    "src/sophyane/"
                    "local_coding_capability.py"
                ),
                "find": (
                    "def check():\n"
                    "    return True\n"
                ),
                "replace": (
                    "def check():\n"
                    "    return add(20, 22) == 42\n"
                ),
            },
        )


def test_indexed_edit_generates_patch_from_numbered_window(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.candidate_evolution import (
        _diff_paths,
        _indexed_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/capability_executors.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def execute(value):\n"
        "    if value is None:\n"
        "        return None\n"
        "    return value\n",
        encoding="utf-8",
    )

    lines = target.read_text(
        encoding="utf-8"
    ).splitlines(
        keepends=True
    )

    patch = _indexed_edit_to_patch(
        repo=tmp_path,
        component="python",
        window={
            "file": (
                "src/sophyane/"
                "capability_executors.py"
            ),
            "offset": 0,
            "lines": lines,
        },
        payload={
            "op": "replace",
            "start": 3,
            "end": 3,
            "code": "        return False",
        },
    )

    assert _diff_paths(patch) == [
        (
            "src/sophyane/"
            "capability_executors.py"
        )
    ]

    assert "-        return None" in patch
    assert "+        return False" in patch


def test_indexed_edit_rejects_range_outside_window(
    tmp_path: Path,
) -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/capability_executors.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="outside the selected window",
    ):
        _indexed_edit_to_patch(
            repo=tmp_path,
            component="python",
            window={
                "file": (
                    "src/sophyane/"
                    "capability_executors.py"
                ),
                "offset": 0,
                "lines": ["value = 1\n"],
            },
            payload={
                "op": "replace",
                "start": 2,
                "end": 2,
                "code": "value = 2",
            },
        )


def test_indexed_edit_payload_is_compact() -> None:
    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_payload,
    )

    payload = _indexed_edit_payload(
        '{"op":"insert_after","start":2,'
        '"end":2,"code":"    verify()"}'
    )

    assert payload["op"] == "insert_after"
    assert payload["start"] == 2
    assert payload["end"] == 2
    assert payload["code"] == "    verify()"


def test_indexed_edit_rejects_schema_placeholder() -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_payload,
    )

    with pytest.raises(
        ValueError,
        match="schema placeholder",
    ):
        _indexed_edit_payload(
            '{"op":"replace","start":2,"end":2,'
            '"code":"maximum five source lines"}'
        )


def test_worktree_cleanliness_detects_generated_file(
    tmp_path: Path,
) -> None:
    import subprocess

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )
    from sophyane.evolution.models import (
        PatchProposal,
    )

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

    source.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    generated = (
        tmp_path
        / "improvements/epoch-test.json"
    )
    generated.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    generated.write_text(
        "{}\n",
        encoding="utf-8",
    )

    proposal = PatchProposal(
        component="python",
        rationale="Test",
        patch=(
            "diff --git "
            "a/src/sophyane/capability_executors.py "
            "b/src/sophyane/capability_executors.py\n"
            "--- a/src/sophyane/capability_executors.py\n"
            "+++ b/src/sophyane/capability_executors.py\n"
            "@@ -1 +1 @@\n"
            "-value = 1\n"
            "+value = 2\n"
        ),
        tests=[],
        confidence=0.9,
        allowed_paths=[
            "src/sophyane/capability_executors.py",
        ],
    )

    evolver = CandidateEvolver(tmp_path)

    clean, unexpected, missing = (
        evolver._worktree_cleanliness(
            worktree=tmp_path,
            proposal=proposal,
        )
    )

    assert clean is False
    assert unexpected == [
        "improvements/epoch-test.json"
    ]
    assert missing == []


def test_worktree_cleanliness_accepts_only_proposal_path(
    tmp_path: Path,
) -> None:
    import subprocess

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )
    from sophyane.evolution.models import (
        PatchProposal,
    )

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

    source.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    proposal = PatchProposal(
        component="python",
        rationale="Test",
        patch=(
            "diff --git "
            "a/src/sophyane/capability_executors.py "
            "b/src/sophyane/capability_executors.py\n"
            "--- a/src/sophyane/capability_executors.py\n"
            "+++ b/src/sophyane/capability_executors.py\n"
            "@@ -1 +1 @@\n"
            "-value = 1\n"
            "+value = 2\n"
        ),
        tests=[],
        confidence=0.9,
        allowed_paths=[
            "src/sophyane/capability_executors.py",
        ],
    )

    evolver = CandidateEvolver(tmp_path)

    clean, unexpected, missing = (
        evolver._worktree_cleanliness(
            worktree=tmp_path,
            proposal=proposal,
        )
    )

    assert clean is True
    assert unexpected == []
    assert missing == []


def test_indexed_edit_inherits_selected_line_indentation(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def run():\n"
        "    result = call(\n"
        "        value=1,\n"
        "        timeout=60,\n"
        "    )\n"
        "    return result\n",
        encoding="utf-8",
    )

    lines = target.read_text(
        encoding="utf-8"
    ).splitlines(
        keepends=True
    )

    patch = _indexed_edit_to_patch(
        repo=tmp_path,
        component="python",
        window={
            "file": (
                "src/sophyane/"
                "local_coding_capability.py"
            ),
            "offset": 0,
            "lines": lines,
        },
        payload={
            "op": "replace",
            "start": 4,
            "end": 4,
            "code": "timeout=120,",
        },
    )

    assert "-        timeout=60," in patch
    assert "+        timeout=120," in patch


def test_indexed_edit_rejects_invalid_python_syntax(
    tmp_path: Path,
) -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def run():\n"
        "    return True\n",
        encoding="utf-8",
    )

    lines = target.read_text(
        encoding="utf-8"
    ).splitlines(
        keepends=True
    )

    with pytest.raises(
        ValueError,
        match="invalid Python syntax",
    ):
        _indexed_edit_to_patch(
            repo=tmp_path,
            component="python",
            window={
                "file": (
                    "src/sophyane/"
                    "local_coding_capability.py"
                ),
                "offset": 0,
                "lines": lines,
            },
            payload={
                "op": "replace",
                "start": 2,
                "end": 2,
                "code": "if True:",
            },
        )


def test_single_statement_rejects_multiline_replacement(
    tmp_path: Path,
) -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def run():\n"
        "    value = 1\n"
        "    return value\n",
        encoding="utf-8",
    )

    lines = target.read_text(
        encoding="utf-8"
    ).splitlines(
        keepends=True
    )

    with pytest.raises(
        ValueError,
        match="single non-block source line",
    ):
        _indexed_edit_to_patch(
            repo=tmp_path,
            component="python",
            window={
                "file": (
                    "src/sophyane/"
                    "local_coding_capability.py"
                ),
                "offset": 0,
                "lines": lines,
            },
            payload={
                "op": "replace",
                "start": 2,
                "end": 2,
                "code": (
                    "value = 2\n"
                    "if value:\n"
                    "    verify(value)"
                ),
            },
        )


def test_single_statement_accepts_single_line_replacement(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.candidate_evolution import (
        _indexed_edit_to_patch,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def run():\n"
        "    value = 1\n"
        "    return value\n",
        encoding="utf-8",
    )

    lines = target.read_text(
        encoding="utf-8"
    ).splitlines(
        keepends=True
    )

    patch = _indexed_edit_to_patch(
        repo=tmp_path,
        component="python",
        window={
            "file": (
                "src/sophyane/"
                "local_coding_capability.py"
            ),
            "offset": 0,
            "lines": lines,
        },
        payload={
            "op": "replace",
            "start": 2,
            "end": 2,
            "code": "value = 2",
        },
    )

    assert "-    value = 1" in patch
    assert "+    value = 2" in patch


def test_indexed_repair_prompt_has_single_line_mode() -> None:
    import inspect

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )

    source = inspect.getsource(
        CandidateEvolver.generate_proposal
    )

    assert "single_line_repair" in source
    assert "exactly one source line" in source
    assert "total response below 80 tokens" in source
    assert "max_tokens=80" in source


def test_indexed_repair_must_preserve_original_range() -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _validate_indexed_repair_anchor,
    )

    window = {
        "lines": [
            "    red = _run(\n",
            "        [sys.executable],\n",
            "        timeout=120,\n",
            "    )\n",
        ]
    }

    with pytest.raises(
        ValueError,
        match="changed the original source range",
    ):
        _validate_indexed_repair_anchor(
            original_payload={
                "op": "replace",
                "start": 3,
                "end": 3,
                "code": "timeout=120,",
            },
            repaired_payload={
                "op": "replace",
                "start": 1,
                "end": 1,
                "code": "def test_addition():",
            },
            window=window,
        )


def test_indexed_repair_rejects_unrelated_source() -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _validate_indexed_repair_anchor,
    )

    window = {
        "lines": [
            "    red = _run(\n",
            "        [sys.executable],\n",
            "        timeout=120,\n",
            "    )\n",
        ]
    }

    with pytest.raises(
        ValueError,
        match="unrelated to the selected source window",
    ):
        _validate_indexed_repair_anchor(
            original_payload={
                "op": "replace",
                "start": 3,
                "end": 3,
                "code": "timeout=120,",
            },
            repaired_payload={
                "op": "replace",
                "start": 3,
                "end": 3,
                "code": "def test_addition():",
            },
            window=window,
        )


def test_indexed_repair_accepts_related_same_range() -> None:
    from sophyane.evolution.candidate_evolution import (
        _validate_indexed_repair_anchor,
    )

    window = {
        "lines": [
            "    red = _run(\n",
            "        [sys.executable],\n",
            "        timeout=120,\n",
            "    )\n",
        ]
    }

    _validate_indexed_repair_anchor(
        original_payload={
            "op": "replace",
            "start": 3,
            "end": 3,
            "code": "timeout=120,",
        },
        repaired_payload={
            "op": "replace",
            "start": 3,
            "end": 3,
            "code": "timeout=90,",
        },
        window=window,
    )


def test_oversized_repair_recovers_unique_valid_line(
    tmp_path: Path,
) -> None:
    from sophyane.evolution.candidate_evolution import (
        _recover_single_line_indexed_edit,
    )

    target = (
        tmp_path
        / "src/sophyane/local_coding_capability.py"
    )
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        "def run():\n"
        "    red = _run(\n"
        "        [sys.executable],\n"
        "        cwd=workspace,\n"
        "        timeout=60,\n"
        "    )\n",
        encoding="utf-8",
    )

    lines = target.read_text(
        encoding="utf-8"
    ).splitlines(
        keepends=True,
    )

    recovered = _recover_single_line_indexed_edit(
        repo=tmp_path,
        component="python",
        window={
            "file": (
                "src/sophyane/"
                "local_coding_capability.py"
            ),
            "offset": 0,
            "lines": lines,
        },
        payload={
            "op": "replace",
            "start": 5,
            "end": 5,
            "code": (
                "red = _run(\n"
                "    [sys.executable],\n"
                "    cwd=workspace,\n"
                "    timeout=120,\n"
                ")"
            ),
        },
    )

    assert recovered["code"].strip() == "timeout=120,"
    assert recovered["single_line_recovered"] is True


def test_single_line_response_accepts_raw_source() -> None:
    from sophyane.evolution.candidate_evolution import (
        _single_line_edit_response,
    )

    assert (
        _single_line_edit_response(
            "timeout=90,"
        )
        == "timeout=90,"
    )


def test_single_line_response_unwraps_fence() -> None:
    from sophyane.evolution.candidate_evolution import (
        _single_line_edit_response,
    )

    assert (
        _single_line_edit_response(
            "```python\n"
            "timeout=90,\n"
            "```"
        )
        == "timeout=90,"
    )


def test_single_line_response_rejects_multiple_lines() -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _single_line_edit_response,
    )

    with pytest.raises(
        ValueError,
        match="exactly one source line",
    ):
        _single_line_edit_response(
            "timeout=90,\n"
            "evidence.append(red)"
        )


def test_single_line_response_rejects_json() -> None:
    import pytest

    from sophyane.evolution.candidate_evolution import (
        _single_line_edit_response,
    )

    with pytest.raises(
        ValueError,
        match="structured output",
    ):
        _single_line_edit_response(
            '{"code":"timeout=90,"}'
        )


def test_generate_proposal_uses_raw_single_line_repair() -> None:
    import inspect

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )

    source = inspect.getsource(
        CandidateEvolver.generate_proposal
    )

    assert "Return only the replacement source text" in source
    assert "repair_max_tokens = 32" in source
    assert "_single_line_edit_response" in source
    assert "raw_single_line_repair" in source
