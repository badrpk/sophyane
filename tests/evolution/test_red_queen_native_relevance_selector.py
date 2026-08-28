from __future__ import annotations

from pathlib import Path

from sophyane.evolution.engine import (
    EvolutionEngine,
)
from sophyane.evolution.models import (
    EvolutionConfig,
    GateResult,
)


def make_engine(
    tmp_path: Path,
) -> EvolutionEngine:
    repo = tmp_path / "repo"
    repo.mkdir()

    return EvolutionEngine(
        EvolutionConfig(
            repo=repo,
            cycles=3,
            allow_candidate_patches=False,
            allow_promotion=False,
        )
    )


def workspace(
    tmp_path: Path,
    patch: str,
) -> Path:
    root = tmp_path / "candidate"

    rq = (
        root
        / "tests"
        / "red_queen"
    )

    rq.mkdir(
        parents=True
    )

    (
        rq
        / "test_targeted_supplemental.py"
    ).write_text(
        '''\
from app.core import normalize_name


def test_whitespace():
    assert normalize_name(" Alice ") == "alice"
''',
        encoding="utf-8",
    )

    (
        rq
        / "test_regression_supplemental.py"
    ).write_text(
        '''\
from app.core import safe_divide


def test_zero():
    assert safe_divide(8, 0) is None
''',
        encoding="utf-8",
    )

    (
        rq
        / "test_security_supplemental.py"
    ).write_text(
        '''\
from app.core import escape_html


def test_ampersand():
    assert escape_html("A&B") == "A&amp;B"
''',
        encoding="utf-8",
    )

    (
        root
        / ".candidate.patch"
    ).write_text(
        patch,
        encoding="utf-8",
    )

    return root


def gate(
    root: Path,
) -> GateResult:
    return GateResult(
        targeted_passed=True,
        regression_passed=True,
        held_out_passed=True,
        baseline_score=1.0,
        candidate_score=3.0,
        security_passed=True,
        promotable=True,
        details={
            "worktree": str(root),
            "candidate_generalization_score":
                1.0,
            "candidate_generalization": {
                "executed": True,
            },
        },
    )


def teach(
    engine: EvolutionEngine,
) -> None:
    for family in (
        "targeted",
        "regression",
        "security",
    ):
        engine.red_queen_execution_policy.learn(
            failures=(
                family
                + " validation failure",
            ),
            epoch=2,
            evaluator_identity=(
                engine.red_queen
                .active.identity()
            ),
        )


def test_changed_patch_tokens_exclude_context():
    patch = '''\
diff --git a/app/core.py b/app/core.py
index 1111111..2222222 100644
--- a/app/core.py
+++ b/app/core.py
@@ -1,6 +1,6 @@
 def normalize_name(value):
-    return value.strip().lower()
+    return value.lower()

 def safe_divide(a, b):
     return a / b
'''

    tokens = (
        EvolutionEngine
        ._red_queen_changed_patch_tokens(
            patch
        )
    )

    assert "normalize_name" not in tokens
    assert "safe_divide" not in tokens

    assert "strip" in tokens
    assert "lower" in tokens
    assert "value" in tokens

    relevance = (
        EvolutionEngine
        ._red_queen_patch_relevance_tokens(
            patch
        )
    )

    assert "normalize_name" in relevance
    assert "safe_divide" not in relevance


def test_context_only_regression_identifier_does_not_select(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    teach(engine)

    root = workspace(
        tmp_path,
        '''\
diff --git a/app/core.py b/app/core.py
index 1111111..2222222 100644
--- a/app/core.py
+++ b/app/core.py
@@ -1,6 +1,6 @@
 def normalize_name(value):
-    return value.strip().lower()
+    return value.lower()

 def safe_divide(a, b):
     return a / b
''',
    )

    current = gate(root)

    selected = (
        engine
        ._select_red_queen_native_challenges(
            current
        )
    )

    families = {
        item.family
        for item in selected
    }

    assert "targeted" in families
    assert "regression" not in families


def test_engine_fixed_paths_only(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    teach(engine)

    for request in engine.red_queen_challenges():
        assert not hasattr(
            request,
            "path",
        )

        assert not hasattr(
            request,
            "command",
        )


def test_selector_cannot_change_promotable(
    tmp_path,
):
    engine = make_engine(
        tmp_path
    )

    teach(engine)

    root = workspace(
        tmp_path,
        '''\
diff --git a/app/core.py b/app/core.py
index 1111111..2222222 100644
--- a/app/core.py
+++ b/app/core.py
@@ -1 +1 @@
-def normalize_name(value):
+def normalize_name(value: str):
''',
    )

    current = gate(root)

    before = current.promotable

    engine._select_red_queen_native_challenges(
        current
    )

    assert current.promotable is before
