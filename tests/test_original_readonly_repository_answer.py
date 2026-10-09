from pathlib import Path

from sophyane import adaptive_execution as adaptive


def test_read_only_repository_inspection_answers_question_after_grounded_command(tmp_path):
    (tmp_path / "observed.txt").write_text("repository evidence\n", encoding="utf-8")
    responses = iter([
        '{"action":{"type":"respond","message":"no implementation target was specified"}}',
    ])

    result = adaptive.run_adaptive_loop(
        initial_text=(
            '{"action":{"type":"run_command",'
            '"command":"find . -maxdepth 1 -type f -print"}}'
        ),
        original_request=(
            "Inspect this repository read-only and answer what files are present. "
            "Do not modify any files."
        ),
        ask=lambda _prompt: next(responses),
        workspace=tmp_path,
        max_steps=3,
    )

    assert "no implementation target was specified" not in result.casefold()
    assert "observed.txt" in result
