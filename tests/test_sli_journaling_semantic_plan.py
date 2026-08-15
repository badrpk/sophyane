from __future__ import annotations

from pathlib import Path

from sophyane.sli_semantic_intelligence import (
    artifact_capability_coverage,
    build_semantic_plan,
)


REQUEST = (
    "Design a lightweight execution journaling mechanism in Python/C++ "
    "that captures non-deterministic async API responses and thread "
    "interleavings. Provide a complete code snippet showing how to replay "
    "a failed execution path with bit-for-bit precision to isolate a "
    "race condition."
)


def test_showing_does_not_match_win_substring() -> None:
    plan = build_semantic_plan(REQUEST)

    validation = [
        item
        for item in plan.capabilities
        if item.name == "rules_and_validation"
    ]

    assert not validation, (
        "rules_and_validation was inferred from the ontology concept "
        "'win' matching as a substring inside 'showing'"
    )


def test_journaling_request_retains_distinguishing_capabilities() -> None:
    plan = build_semantic_plan(REQUEST)
    names = set(plan.required_names)

    assert plan.has_material_requirement is True

    assert "execution_journaling" in names
    assert "concurrency_coordination" in names
    assert "deterministic_replay" in names

    assert "entry_point" in names
    assert "error_handling" in names


def test_unrelated_validation_program_cannot_claim_full_coverage(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "main.py"

    artifact.write_text(
        """
def check_item(condition):
    if condition:
        return True
    return False

def main():
    try:
        check_item(True)
    except Exception:
        raise

if __name__ == "__main__":
    main()
""",
        encoding="utf-8",
    )

    plan = build_semantic_plan(REQUEST)

    coverage, coverage_map, missing = artifact_capability_coverage(
        plan,
        [artifact],
    )

    assert coverage < 1.0
    assert missing

    assert not (
        coverage_map.get("execution_journaling", False)
        and coverage_map.get("concurrency_coordination", False)
        and coverage_map.get("deterministic_replay", False)
    )


def test_generic_architecture_cannot_manufacture_semantic_coverage(
    tmp_path: Path,
) -> None:
    request = (
        "Write a Python program implementing a completely novel "
        "specialized frobnication mechanism."
    )

    plan = build_semantic_plan(request)

    # No ontology capability understands "frobnication"; only architectural
    # requirements may remain.
    assert plan.has_material_requirement is False

    artifact = tmp_path / "main.py"
    artifact.write_text(
        """
def main():
    try:
        return 0
    except Exception:
        raise

if __name__ == "__main__":
    main()
""",
        encoding="utf-8",
    )

    coverage, _, _ = artifact_capability_coverage(
        plan,
        [artifact],
    )

    assert coverage == 0.0


def test_browser_request_does_not_reintroduce_substring_concepts() -> None:
    plan = build_semantic_plan(
        "Build a browser snake game using canvas and JavaScript."
    )

    by_name = {
        item.name: item
        for item in plan.capabilities
    }

    # Historical substring matching produced:
    #     "ui" in "using"
    #     "script" in "javascript"
    #
    # Those false concepts inflated semantic importance and changed plan
    # provenance. Boundary-safe matching must keep only legitimate reasons.
    assert by_name["document_shell"].reasons == [
        "browser",
    ]

    assert by_name["presentation"].reasons == [
        "game",
    ]

    assert by_name["entry_point"].reasons == [
        "architectural dependency",
    ]
