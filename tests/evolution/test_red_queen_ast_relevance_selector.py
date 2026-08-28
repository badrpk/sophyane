from __future__ import annotations

from pathlib import Path

from sophyane.evolution.engine import (
    EvolutionEngine,
)


def test_comment_spoof_identifiers_are_excluded():
    patch = '''\
diff --git a/app/core.py b/app/core.py
--- a/app/core.py
+++ b/app/core.py
@@ -1,3 +1,4 @@ def normalize_name(value):
+    # safe_divide escape_html regression security
     return value.strip().lower()
'''

    relevance = (
        EvolutionEngine
        ._red_queen_patch_relevance_tokens(
            patch
        )
    )

    assert "normalize_name" in relevance

    assert "safe_divide" not in relevance
    assert "escape_html" not in relevance
    assert "regression" not in relevance
    assert "security" not in relevance


def test_string_spoof_identifiers_are_excluded():
    patch = '''\
diff --git a/app/core.py b/app/core.py
--- a/app/core.py
+++ b/app/core.py
@@ -1,3 +1,4 @@ def normalize_name(value):
+    marker = "safe_divide escape_html"
     return value.strip().lower()
'''

    relevance = (
        EvolutionEngine
        ._red_queen_patch_relevance_tokens(
            patch
        )
    )

    assert "normalize_name" in relevance
    assert "marker" in relevance

    assert "safe_divide" not in relevance
    assert "escape_html" not in relevance


def test_no_hunk_function_tail_recovers_from_candidate_source(
    tmp_path: Path,
):
    worktree = tmp_path / "candidate"

    source = (
        worktree
        / "app"
        / "core.py"
    )

    source.parent.mkdir(
        parents=True
    )

    source.write_text(
        '''\
def normalize_name(value):
    return value.lower()
''',
        encoding="utf-8",
    )

    patch = '''\
diff --git a/app/core.py b/app/core.py
--- a/app/core.py
+++ b/app/core.py
@@ -2,1 +2,1 @@
-    return value.strip().lower()
+    return value.lower()
'''

    relevance = (
        EvolutionEngine
        ._red_queen_patch_relevance_tokens(
            patch,
            worktree=worktree,
        )
    )

    assert "normalize_name" in relevance


def test_class_method_recovers_most_specific_symbol(
    tmp_path: Path,
):
    worktree = tmp_path / "candidate"

    source = (
        worktree
        / "app"
        / "core.py"
    )

    source.parent.mkdir(
        parents=True
    )

    source.write_text(
        '''\
class Normalizer:
    def normalize_name(self, value):
        return value.lower()
''',
        encoding="utf-8",
    )

    patch = '''\
diff --git a/app/core.py b/app/core.py
--- a/app/core.py
+++ b/app/core.py
@@ -3,1 +3,1 @@
-        return value.strip().lower()
+        return value.lower()
'''

    relevance = (
        EvolutionEngine
        ._red_queen_patch_relevance_tokens(
            patch,
            worktree=worktree,
        )
    )

    assert "normalize_name" in relevance


def test_candidate_patch_cannot_escape_worktree(
    tmp_path: Path,
):
    worktree = tmp_path / "candidate"
    worktree.mkdir()

    outside = tmp_path / "outside.py"

    outside.write_text(
        '''\
def dangerous():
    return 1
''',
        encoding="utf-8",
    )

    patch = '''\
diff --git a/../outside.py b/../outside.py
--- a/../outside.py
+++ b/../outside.py
@@ -2,1 +2,1 @@
-    return 0
+    return 1
'''

    symbols = (
        EvolutionEngine
        ._red_queen_candidate_enclosing_symbols(
            worktree=worktree,
            patch=patch,
        )
    )

    assert symbols == frozenset()


def test_changed_token_surface_excludes_literal_contents():
    patch = '''\
diff --git a/app/core.py b/app/core.py
--- a/app/core.py
+++ b/app/core.py
@@ -1 +1 @@
-marker = ""
+marker = "safe_divide escape_html"
'''

    tokens = (
        EvolutionEngine
        ._red_queen_changed_python_tokens(
            patch
        )
    )

    assert "marker" in tokens
    assert "safe_divide" not in tokens
    assert "escape_html" not in tokens
