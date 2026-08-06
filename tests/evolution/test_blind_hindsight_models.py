from sophyane.evolution.models import (
    FeedbackReport,
)


def test_feedback_supports_mismatch_and_principle() -> None:
    report = FeedbackReport(
        kind="hindsight",
        author="gemini",
        summary="The route was wrong.",
        mismatch=(
            "The actor believed it selected private data, "
            "but the validator observed public acquisition."
        ),
        general_principle=(
            "Ownership questions must be classified before "
            "public acquisition."
        ),
    )

    assert report.mismatch
    assert report.general_principle
