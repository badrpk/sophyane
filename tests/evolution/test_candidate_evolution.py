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
