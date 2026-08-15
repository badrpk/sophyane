from __future__ import annotations

from pathlib import Path
import ast

from sophyane.sli_semantic_intelligence import (
    build_semantic_plan,
)


def _capabilities(
    request: str,
) -> list[str]:
    return [
        item.name
        for item in build_semantic_plan(
            request
        ).capabilities
    ]


def test_only_one_semantic_plan_definition():
    path = Path(
        "src/sophyane/sli_semantic_intelligence.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        text
    )

    nodes = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "build_semantic_plan"
        )
    ]

    assert len(nodes) == 1

    assert (
        "_SLI_ORIGINAL_BUILD_SEMANTIC_PLAN"
        not in text
    )

    assert (
        "_FINAL_ORIGINAL_BUILD_PLAN"
        not in text
    )


def test_python_semantic_plan_is_preserved():
    plan = build_semantic_plan(
        (
            "Write Python code for a deterministic "
            "execution journal with replay."
        )
    )

    assert plan.target_language == "python"

    assert (
        plan.target_artifact
        == "python_application"
    )

    # Journaling/replay are now first-class behavioral capabilities.
    # Architectural entry/error duties remain implementation dependencies.
    assert [
        item.name
        for item in plan.capabilities
    ] == [
        "deterministic_replay",
        "execution_journaling",
        "entry_point",
        "error_handling",
    ]

    assert plan.has_material_requirement is True


def test_browser_game_semantic_plan_is_preserved():
    plan = build_semantic_plan(
        (
            "Build a browser snake game using "
            "canvas and JavaScript."
        )
    )

    assert (
        plan.target_language
        == "javascript"
    )

    assert (
        plan.target_artifact
        == "browser_application"
    )

    names = [
        item.name
        for item in plan.capabilities
    ]

    # Boundary-safe matching intentionally removes historical false
    # positives such as "ui" inside "using" and "script" inside
    # "JavaScript". Ordering therefore reflects the corrected importance
    # values rather than the old substring-inflated scores.
    assert names == [
        "rendering",
        "application_state",
        "rules_and_validation",
        "user_input",
        "time_loop",
        "document_shell",
        "lifecycle_control",
        "presentation",
        "progress_feedback",
        "entry_point",
    ]

    assert "http_endpoint" not in names
    assert "web_server" not in names
    assert "error_handling" not in names


def test_browser_website_semantic_plan_is_preserved():
    plan = build_semantic_plan(
        (
            "Create a responsive website "
            "for a solar company."
        )
    )

    assert [
        item.name
        for item in plan.capabilities
    ] == [
        "document_shell",
        "presentation",
        "application_state",
        "entry_point",
    ]


def test_explicit_http_endpoint_is_preserved():
    names = _capabilities(
        (
            "Create a local HTTP API endpoint "
            "that returns JSON."
        )
    )

    assert "http_endpoint" in names


def test_nonserver_api_reference_does_not_force_endpoint():
    names = _capabilities(
        (
            "Write Python code that calls an external "
            "API and records the JSON response."
        )
    )

    assert "http_endpoint" not in names


def test_cpp_current_semantic_behavior_is_not_changed():
    plan = build_semantic_plan(
        (
            "Implement a deterministic execution journal "
            "in C++ using std::thread std::mutex and replay."
        )
    )

    # C++ target inference is intentionally a separate follow-up.
    assert plan.target_language is None
    assert plan.target_artifact is None
    assert plan.capabilities == []


def test_rust_current_semantic_behavior_is_not_changed():
    plan = build_semantic_plan(
        "Implement a Rust command line JSON parser."
    )

    # Rust inference is intentionally outside this consolidation.
    assert plan.target_language is None
    assert plan.target_artifact is None
    assert plan.capabilities == []
