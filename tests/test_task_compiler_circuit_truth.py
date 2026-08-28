from sophyane.task_compiler import (
    Requirement,
    validate_requirement_evidence,
)


def requirement():
    return Requirement(
        requirement_id="r1",
        text=(
            "Integrate a circuit breaker around the primary "
            "payment gateway HTTP client. Set the threshold "
            "to open after 5 consecutive HTTP 5xx errors or "
            "timeouts within a 30 second window, falling back "
            "to the secondary payment processor."
        ),
        difficulty=4,
    )


def test_conflicting_timeout_count_is_rejected():
    value = """
    {
      "state": "OPEN",
      "error_count": 5,
      "timeout_count": 3,
      "window": 30,
      "failure": "HTTP 5xx or timeout",
      "fallback": "secondary payment processor"
    }
    """

    valid, detail = (
        validate_requirement_evidence(
            requirement(),
            value,
        )
    )

    assert not valid
    assert (
        "conflicting timeout threshold"
        in detail
    )


def test_shared_five_failure_threshold_is_valid():
    value = (
        "OPEN after 5 consecutive HTTP 5xx or timeout "
        "failures within 30 seconds; fallback to the "
        "secondary payment processor."
    )

    valid, detail = (
        validate_requirement_evidence(
            requirement(),
            value,
        )
    )

    assert valid, detail


def test_missing_5xx_is_rejected():
    value = (
        "OPEN after 5 consecutive timeout failures within "
        "30 seconds; fallback to the secondary payment processor."
    )

    valid, detail = (
        validate_requirement_evidence(
            requirement(),
            value,
        )
    )

    assert not valid
    assert "5xx" in detail
