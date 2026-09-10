from sophyane.browser_partial_recovery import (
    _quality_rank,
    _reconcile_visual_repair_code,
)


def report(
    *,
    score,
    critical=1,
    unmet=1,
    code="MULTIPLE_ISSUES",
    images=4,
    broken=0,
    console=0,
    logs=0,
    overflow=False,
    required=True,
):
    return {
        "accepted": False,
        "score": score,
        "critical_issues": critical,
        "unmet_requirements": unmet,
        "repair_code": code,
        "render_facts": {
            "images": images,
            "broken_images": broken,
            "console_errors": console,
            "log_errors": logs,
            "horizontal_overflow": overflow,
            "required_images": required,
        },
    }


def test_clean_lower_score_beats_missing_required_images():
    missing = report(score=82, images=0)
    clean = report(score=74, images=14)

    assert _quality_rank(clean) > _quality_rank(missing)


def test_higher_score_wins_when_render_and_issue_counts_equal():
    a = report(score=74, images=14)
    b = report(score=62, images=10)

    assert _quality_rank(a) > _quality_rank(b)


def test_broken_images_code_cannot_contradict_renderer():
    value = report(
        score=74,
        code="BROKEN_IMAGES",
        images=14,
        broken=0,
    )

    fixed = _reconcile_visual_repair_code(value)

    assert fixed["repair_code"] == "MULTIPLE_ISSUES"
    assert "zero broken images" in fixed["summary"]


def test_real_broken_images_code_is_preserved():
    value = report(
        score=74,
        code="BROKEN_IMAGES",
        images=14,
        broken=2,
    )

    fixed = _reconcile_visual_repair_code(value)

    assert fixed["repair_code"] == "BROKEN_IMAGES"


def test_stale_render_code_is_not_accepted_from_visual_guess():
    value = report(
        score=62,
        code="STALE_RENDER_EVIDENCE",
    )

    fixed = _reconcile_visual_repair_code(value)

    assert fixed["repair_code"] == "MULTIPLE_ISSUES"
    assert "staleness" in fixed["summary"].lower()
