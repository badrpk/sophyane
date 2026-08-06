from pathlib import Path

from sophyane.evolution.engine import (
    EvolutionEngine,
)
from sophyane.evolution.models import (
    EvolutionConfig,
    PatchProposal,
)


def test_patch_restricted_to_one_component(
    tmp_path: Path,
) -> None:
    engine = EvolutionEngine(
        EvolutionConfig(
            repo=tmp_path,
        )
    )

    allowed = PatchProposal(
        component="semantic_router",
        rationale="general fix",
        patch=(
            "diff --git "
            "a/src/sophyane/semantic_intent_router.py "
            "b/src/sophyane/semantic_intent_router.py\n"
            "--- a/src/sophyane/semantic_intent_router.py\n"
            "+++ b/src/sophyane/semantic_intent_router.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        ),
        tests=[],
        confidence=0.9,
        allowed_paths=[
            "src/sophyane/semantic_intent_router.py",
        ],
    )

    assert engine._patch_allowed(
        allowed
    ) is True

    forbidden = PatchProposal(
        component="semantic_router",
        rationale="bad",
        patch=(
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        ),
        tests=[],
        confidence=0.9,
        allowed_paths=[
            "src/sophyane/semantic_intent_router.py",
        ],
    )

    assert engine._patch_allowed(
        forbidden
    ) is False
