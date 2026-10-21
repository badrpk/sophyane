from sophyane.cli_entry import build_host_live_core_controller
from sophyane.core_controller.models import ControllerRequest, ModeName


def test_host_runtime_binds_proven_local_and_codex_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)
    monkeypatch.setattr("sophyane.providers.codex_cli.agy_available", lambda: True)

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    status = controller.readiness()

    assert status["modes"][ModeName.LOCAL_LLM.value]["ready"] is True
    assert status["modes"][ModeName.EXTERNAL_LLM.value]["ready"] is True
    assert status["modes"][ModeName.HUMAN_CONVERSATION.value]["ready"] is True
    assert status["modes"][ModeName.RACE.value]["ready"] is True
    assert status["modes"][ModeName.SLI_GRAPH.value]["ready"] is True
    assert status["modes"][ModeName.LEARNING.value]["ready"] is True


def test_host_runtime_local_handler_uses_llama_provider(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)
    monkeypatch.setattr("sophyane.providers.local_gguf.LocalGgufProvider.generate", lambda self, prompt, system_prompt: "local:" + prompt)

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    result = controller.handle(
        ControllerRequest(text="hello local", requested_mode=ModeName.LOCAL_LLM)
    )

    assert result.disposition == "completed", result.to_dict()
    assert result.output == "local:hello local"


def test_host_runtime_sli_handler_builds_deterministic_plan(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    result = controller.handle(
        ControllerRequest(text="build a python tool", requested_mode=ModeName.SLI_GRAPH)
    )

    assert result.disposition == "completed"
    assert result.output.target_language == "python"


def test_host_runtime_learning_handler_submits_bounded_observation(tmp_path, monkeypatch):
    monkeypatch.setattr("sophyane.local_runtime.llama_server_reachable", lambda: True)

    controller = build_host_live_core_controller(audit_path=tmp_path / "audit.jsonl")
    result = controller.handle(
        ControllerRequest(
            text="record provider timeout",
            requested_mode=ModeName.LEARNING,
            context={"evidence": {"component": "provider", "evidence": ["timeout"]}},
        )
    )

    assert result.disposition == "completed"
    assert result.output["accepted"] is True
