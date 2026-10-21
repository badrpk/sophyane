from sophyane.core_controller.curriculum_bridge import ObservationCurriculumBridge
from sophyane.rsi.observation_bus import ImprovementObservation, ImprovementSource


def test_provider_observation_creates_specific_scope_and_test(tmp_path):
    bridge = ObservationCurriculumBridge(tmp_path / "curriculum.json")
    observation = ImprovementObservation(
        ImprovementSource.RUNTIME,
        "provider timeout recovery is weak",
        "provider_gateway",
        ("timeout observed",),
    )

    bridge.enqueue_observation(observation)
    task = bridge.store.load().queue[0]

    assert task.editable_paths == ("src/sophyane/core_controller/provider_gateway.py",)
    assert task.verification == ("PYTHONPATH=src .venv/bin/pytest -q tests/test_core_controller_provider_gateway.py",)
    assert task.review_status == "pending"
