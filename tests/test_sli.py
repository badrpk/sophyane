from pathlib import Path

from sophyane import sli
from sophyane.sli_learner import calculate_quality_reward, classify_action


def test_execution_memory_outranks_scanned_logs(tmp_path: Path) -> None:
    with sli.connect(tmp_path / "sli.db") as db:
        for _ in range(20):
            sli.record(
                db,
                request="make a calculator",
                action="INSPECT_EVIDENCE",
                reward=1.0,
                source_type="scanned_log",
            )
        for _ in range(2):
            sli.record(
                db,
                request="make a calculator",
                action="GENERATE_BROWSER_ARTIFACT",
                reward=1.0,
                source_type="execution",
            )
        recommendations = sli.recommend_actions(
            db,
            request="make a simple calculator",
        )
    assert recommendations[0]["action"] == "GENERATE_BROWSER_ARTIFACT"


def test_verified_browser_success_receives_full_reward() -> None:
    reward, signals, category = calculate_quality_reward(
        status="succeeded",
        result=(
            "Browser artifact passed structural verification; "
            "opening verified browser preview. Project completed successfully."
        ),
        workspace_before={"sample": []},
        workspace_after={"sample": [{"path": "index.html", "bytes": 1458}]},
    )
    assert reward == 1.0
    assert category == ""
    assert "artifact_created:+0.20" in signals
    assert "validation_passed:+0.20" in signals


def test_unusable_response_is_categorized() -> None:
    reward, signals, category = calculate_quality_reward(
        status="failed",
        result=(
            "Execution stopped safely: provider could not produce a usable artifact. "
            "Previous working files were preserved."
        ),
        workspace_before={"sample": []},
        workspace_after={"sample": []},
    )
    assert category == "UNUSABLE_PROVIDER_RESPONSE"
    assert reward == -0.5
    assert "safe_failure_preservation:+0.10" in signals


def test_browser_requests_use_browser_action() -> None:
    assert classify_action("make a responsive tip calculator") == "GENERATE_BROWSER_ARTIFACT"
    assert classify_action("explain a repository") == "EXECUTE_STRUCTURED_TASK"
