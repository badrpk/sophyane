from dataclasses import dataclass
from pathlib import Path

from sophyane.goal_execution import (
    ActionResult,
    GoalNode,
    file_exists_validator,
    html_structure_validator,
)
from sophyane.goal_runtime import (
    execute_planner_output,
    planner_goals,
    run_legacy_runtime,
    run_verified_post_build_menu,
)


def valid_html() -> str:
    return "<!doctype html><html><body>Ready</body></html>"


def test_direct_goal_output_is_recognized(tmp_path: Path) -> None:
    goal = GoalNode(
        key="entry",
        description="index exists",
        validator=file_exists_validator("index.html"),
    )

    assert planner_goals([goal]) == (goal,)
    assert planner_goals("not goals") is None
    assert planner_goals({"goals": [goal]}) is None


@dataclass
class NewPlan:
    goals: tuple[GoalNode, ...]


def test_plan_object_goals_are_recognized(tmp_path: Path) -> None:
    goal = GoalNode(
        key="entry",
        description="index exists",
        validator=file_exists_validator("index.html"),
    )

    assert planner_goals(NewPlan((goal,))) == (goal,)


def test_goal_runtime_generates_and_verifies_browser_app(
    tmp_path: Path,
) -> None:
    def generate(context, goal):
        del goal
        (context.workspace / "index.html").write_text(
            valid_html(),
            encoding="utf-8",
        )
        return ActionResult(
            changed=True,
            summary="Generated browser entry.",
            confidence=1.0,
        )

    goals = (
        GoalNode(
            key="entry",
            description="index.html exists",
            validator=file_exists_validator("index.html"),
            action=generate,
            priority=10,
        ),
        GoalNode(
            key="structure",
            description="HTML is structurally complete",
            validator=html_structure_validator("index.html"),
            action=generate,
            dependencies=("entry",),
            priority=20,
        ),
    )

    result = execute_planner_output(
        request="Create browser app",
        workspace=tmp_path,
        planner_output=goals,
    )

    assert result.mode == "goal"
    assert result.achieved is True
    assert result.may_show_success_menu is True
    assert result.goal_report is not None
    assert result.goal_report.achieved is True


def test_goal_report_cannot_override_missing_final_artifact(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "marker.txt"

    def create_marker(context, goal):
        del goal
        marker.write_text("done", encoding="utf-8")
        return ActionResult(
            changed=True,
            summary="Created marker only.",
        )

    goal = GoalNode(
        key="marker",
        description="Marker exists",
        validator=file_exists_validator("marker.txt"),
        action=create_marker,
    )

    result = execute_planner_output(
        request="Create browser app",
        workspace=tmp_path,
        planner_output=(goal,),
    )

    assert result.goal_report is not None
    assert result.goal_report.achieved is True
    assert result.achieved is False
    assert result.may_show_success_menu is False
    assert "completion evidence failed" in result.reason.lower()


def test_legacy_runtime_accepts_verified_artifact(
    tmp_path: Path,
) -> None:
    def legacy():
        (tmp_path / "index.html").write_text(
            valid_html(),
            encoding="utf-8",
        )
        return "legacy complete"

    result = run_legacy_runtime(
        workspace=tmp_path,
        legacy_runner=legacy,
    )

    assert result.mode == "legacy"
    assert result.achieved is True
    assert result.legacy_result == "legacy complete"


def test_legacy_runtime_rejects_false_positive(
    tmp_path: Path,
) -> None:
    def legacy():
        (tmp_path / "provider-response.txt").write_text(
            "claimed success",
            encoding="utf-8",
        )
        return True

    result = run_legacy_runtime(
        workspace=tmp_path,
        legacy_runner=legacy,
    )

    assert result.achieved is False
    assert result.may_show_success_menu is False
    assert "completion evidence failed" in result.reason.lower()


def test_legacy_explicit_false_remains_failure(
    tmp_path: Path,
) -> None:
    def legacy():
        (tmp_path / "index.html").write_text(
            valid_html(),
            encoding="utf-8",
        )
        return False

    result = run_legacy_runtime(
        workspace=tmp_path,
        legacy_runner=legacy,
    )

    assert result.achieved is False
    assert "explicitly reported failure" in result.reason.lower()


def test_missing_legacy_runner_is_safe_failure(
    tmp_path: Path,
) -> None:
    result = execute_planner_output(
        request="Unknown plan",
        workspace=tmp_path,
        planner_output={"steps": ["legacy"]},
    )

    assert result.mode == "unsupported"
    assert result.achieved is False


def test_menu_is_withheld_for_incomplete_result(
    tmp_path: Path,
) -> None:
    messages: list[str] = []

    result = execute_planner_output(
        request="Incomplete project",
        workspace=tmp_path,
        planner_output={"legacy": True},
    )

    outcome = run_verified_post_build_menu(
        result,
        input_fn=lambda _: "0",
        output_fn=messages.append,
    )

    assert outcome == "incomplete"
    assert any("withheld" in message.lower() for message in messages)


def test_infer_capability_requirements_for_browser_request() -> None:
    from sophyane.goal_runtime import infer_capability_requirements

    requirements = infer_capability_requirements(
        "Build a responsive HTML browser game with JavaScript tests"
    )

    assert {"browser", "html", "css", "javascript", "testing"} <= requirements


def test_select_runtime_capability_prefers_browser() -> None:
    from sophyane.goal_runtime import select_runtime_capability

    match = select_runtime_capability(
        "Build a responsive HTML and JavaScript web app"
    )

    assert match is not None
    assert match.capability.name == "browser"
    assert "html" in match.matched
    assert "javascript" in match.matched


def test_select_runtime_capability_falls_back_to_partial_match() -> None:
    from sophyane.capability_manager import Capability, CapabilityManager
    from sophyane.goal_runtime import select_runtime_capability

    manager = CapabilityManager()
    manager.register(
        Capability(
            name="html-only",
            description="HTML generator",
            supports=frozenset({"html"}),
            priority=50,
        )
    )

    match = select_runtime_capability(
        "Build an HTML page with JavaScript",
        manager=manager,
    )

    assert match is not None
    assert match.capability.name == "html-only"
    assert match.missing


def test_select_runtime_capability_returns_none_without_requirements() -> None:
    from sophyane.goal_runtime import select_runtime_capability

    assert select_runtime_capability("Explain this idea") is None
