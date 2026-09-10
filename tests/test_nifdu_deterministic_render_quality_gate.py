from types import SimpleNamespace

from sophyane.browser_partial_recovery import (
    _apply_render_quality_gate,
)


def report(**updates):
    value = {
        "accepted": True,
        "score": 98,
        "critical_issues": 0,
        "unmet_requirements": 0,
        "repair_code": "NONE",
    }
    value.update(updates)
    return value


def rendered(
    *,
    images=4,
    broken_images=0,
    console_errors=0,
    log_errors=0,
    horizontal_overflow=False,
):
    return SimpleNamespace(
        images=images,
        broken_images=broken_images,
        console_errors=console_errors,
        log_errors=log_errors,
        horizontal_overflow=horizontal_overflow,
    )


def test_clean_render_preserves_acceptance():
    result = _apply_render_quality_gate(
        report(),
        rendered(),
        "make a premium dogs website",
    )
    assert result["accepted"] is True
    assert result["repair_code"] == "NONE"


def test_required_photography_with_zero_images_blocks_acceptance():
    result = _apply_render_quality_gate(
        report(),
        rendered(images=0),
        "make a dogs website with professional dog photography",
    )
    assert result["accepted"] is False
    assert result["unmet_requirements"] >= 1
    assert result["repair_code"] == "MISSING_REQUIRED_CONTENT"
    assert result["render_facts"]["required_images"] is True


def test_broken_images_block_model_acceptance():
    result = _apply_render_quality_gate(
        report(),
        rendered(images=4, broken_images=1),
        "make a dogs website",
    )
    assert result["accepted"] is False
    assert result["critical_issues"] >= 1
    assert result["repair_code"] == "BROKEN_IMAGES"


def test_console_errors_block_model_acceptance():
    result = _apply_render_quality_gate(
        report(),
        rendered(console_errors=2),
        "make a dogs website",
    )
    assert result["accepted"] is False
    assert result["repair_code"] == "INTERACTION_FAILURE"


def test_horizontal_overflow_blocks_model_acceptance():
    result = _apply_render_quality_gate(
        report(),
        rendered(horizontal_overflow=True),
        "make a dogs website",
    )
    assert result["accepted"] is False
    assert result["repair_code"] == "RESPONSIVE_LAYOUT"


def test_multiple_render_failures_use_multiple_issues():
    result = _apply_render_quality_gate(
        report(),
        rendered(
            images=0,
            broken_images=1,
            horizontal_overflow=True,
        ),
        "make a dogs website with professional photography",
    )
    assert result["accepted"] is False
    assert result["repair_code"] == "MULTIPLE_ISSUES"
