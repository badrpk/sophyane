import json

from sophyane.cli_entry import build_host_live_core_controller
from sophyane.core_controller.models import ControllerRequest, ModeName


def test_learning_persists_next_curriculum_task(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)
    state_path = tmp_path / "curriculum.json"
    monkeypatch.setenv("SOPHYANE_CURRICULUM_STATE", str(state_path))

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    result = controller.handle(
        ControllerRequest(
            text="improve provider timeout recovery",
            requested_mode=ModeName.LEARNING,
            context={
                "evidence": {
                    "component": "provider_gateway",
                    "problem": "provider timeout recovery is weak",
                    "evidence": ["timeout observed"],
                }
            },
        )
    )

    assert result.disposition == "completed", result.to_dict()
    assert result.output["task_enqueued"] is True
    payload = json.loads(state_path.read_text())
    assert payload["queue"][0]["source"] == "weakness"
    assert "provider timeout recovery" in payload["queue"][0]["objective"]


def test_duplicate_learning_observation_does_not_duplicate_task(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)
    monkeypatch.setenv("SOPHYANE_CURRICULUM_STATE", str(tmp_path / "curriculum.json"))

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    request = ControllerRequest(
        text="improve provider timeout recovery",
        requested_mode=ModeName.LEARNING,
        context={"evidence": {"component": "provider_gateway", "evidence": ["timeout observed"]}},
    )
    first = controller.handle(request)
    second = controller.handle(request)

    assert first.output["task_enqueued"] is True
    assert second.output["task_enqueued"] is False
    payload = json.loads((tmp_path / "curriculum.json").read_text())
    assert len(payload["queue"]) == 1
