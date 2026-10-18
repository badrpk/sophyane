from pathlib import Path

from sophyane.rsi.curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore
from sophyane.rsi.curriculum_runtime import ContinuousCurriculumRuntime


def test_runtime_status_reports_live_promotion(tmp_path: Path):
    state = tmp_path / "promotion.json"
    state.write_text(
        '{"event":"promotion_verified","active_commit":"abc123",'
        '"checkpoint_commit":"old123","promoted":true}\n',
        encoding="utf-8",
    )
    runtime = ContinuousCurriculumRuntime(
        tmp_path,
        object(),
        CurriculumScheduler(CurriculumStore(tmp_path / "curriculum.json"), CurriculumPolicy()),
        enabled=True,
    )

    status = runtime.status()

    assert status["promotion"]["active_commit"] == "abc123"
    assert status["promotion"]["promoted"] is True
