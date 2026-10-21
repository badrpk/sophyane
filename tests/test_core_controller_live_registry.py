from sophyane.cli_entry import build_live_core_controller
from sophyane.core_controller.models import ModeName


def test_live_controller_reports_readiness_without_executing_handlers(tmp_path):
    calls = []
    dependencies = {
        mode: {
            "handler": lambda plan, capability, mode=mode: calls.append(mode) or {"mode": mode.value},
            "ready": True,
        }
        for mode in ModeName
    }

    controller = build_live_core_controller(
        dependencies=dependencies,
        audit_path=tmp_path / "audit.jsonl",
    )
    status = controller.readiness()

    assert set(status["modes"]) == {mode.value for mode in ModeName}
    assert all(item["ready"] for item in status["modes"].values())
    assert calls == []


def test_missing_live_dependencies_are_explicitly_unavailable(tmp_path):
    controller = build_live_core_controller(audit_path=tmp_path / "audit.jsonl")

    status = controller.readiness()

    assert all(not item["ready"] for item in status["modes"].values())
    assert all(item["reason"] for item in status["modes"].values())


def test_readiness_does_not_create_execution_artifacts(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    controller = build_live_core_controller(audit_path=audit_path)

    controller.readiness()

    assert not audit_path.exists()
