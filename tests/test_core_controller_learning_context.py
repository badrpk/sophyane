import json

from sophyane.cli_entry import build_host_live_core_controller
from sophyane.core_controller.models import ControllerRequest, ModeName


def test_learning_uses_request_context_component_for_curriculum_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)
    monkeypatch.setenv("SOPHYANE_CURRICULUM_STATE", str(tmp_path / "curriculum.json"))

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    result = controller.handle(ControllerRequest(
        text="improve retry handling",
        requested_mode=ModeName.LEARNING,
        context={"evidence": {"component": "provider_gateway", "evidence": ["timeout"]}},
    ))

    assert result.output["task_enqueued"] is True
    task = json.loads((tmp_path / "curriculum.json").read_text())["queue"][0]
    assert task["editable_paths"] == ["src/sophyane/core_controller/provider_gateway.py"]
