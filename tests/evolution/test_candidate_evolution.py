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

