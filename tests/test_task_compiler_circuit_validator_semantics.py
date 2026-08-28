from sophyane.task_compiler import (
    Requirement,
    validate_requirement_evidence,
)


REQ = Requirement(
    requirement_id="r1",
    text=(
        "Integrate a circuit breaker around the primary payment gateway "
        "HTTP client. Open after 5 consecutive 5xx errors or timeouts "
        "within a 30s window and fall back to the secondary processor."
    ),
    difficulty=3,
    explicit_facts=(
        "5",
        "30s",
        "architecture:circuit_breaker",
    ),
)


def validate(value: str):
    return validate_requirement_evidence(
        REQ,
        value,
    )


def test_literal_fallback_still_valid():
    valid, detail = validate(
        "Circuit breaker state: CLOSED -> OPEN. "
        "Open after 5 consecutive HTTP 5xx or timeout failures "
        "within 30 seconds. When OPEN, fallback to the secondary "
        "payment processor."
    )

    assert valid
    assert detail == "circuit_breaker"


def test_semantic_secondary_routing_is_valid():
    valid, detail = validate(
        "Wrap the primary payment gateway HTTP client in a circuit breaker. "
        "Track consecutive HTTP 5xx responses and timeout failures. "
        "After 5 consecutive failures within 30 seconds transition from "
        "CLOSED to OPEN. While OPEN, do not call the primary; send the "
        "request to the secondary payment processor."
    )

    assert valid
    assert detail == "circuit_breaker"


def test_route_to_secondary_is_valid():
    valid, detail = validate(
        "After 5 consecutive HTTP 5xx or timeout failures within "
        "30 seconds, transition the breaker to OPEN and route requests "
        "to the secondary payment processor."
    )

    assert valid
    assert detail == "circuit_breaker"


def test_secondary_mention_without_behavior_is_invalid():
    valid, detail = validate(
        "The circuit breaker becomes OPEN after 5 consecutive HTTP 5xx "
        "or timeout failures within 30 seconds. There is also a secondary "
        "payment processor."
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence lacks state/fallback behavior"
    )


def test_missing_5xx_remains_invalid():
    valid, detail = validate(
        "After 5 consecutive timeout failures within 30 seconds, "
        "transition to OPEN and route requests to the secondary "
        "payment processor."
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence omitted HTTP 5xx failures"
    )


def test_missing_timeout_remains_invalid():
    valid, detail = validate(
        "After 5 consecutive HTTP 5xx failures within 30 seconds, "
        "transition to OPEN and route requests to the secondary "
        "payment processor."
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence omitted timeout failures"
    )


def test_wrong_threshold_remains_invalid():
    valid, detail = validate(
        "After 4 consecutive HTTP 5xx or timeout failures within "
        "30 seconds, transition to OPEN and route requests to the "
        "secondary payment processor."
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence omitted failure threshold"
    )


def test_wrong_window_remains_invalid():
    valid, detail = validate(
        "After 5 consecutive HTTP 5xx or timeout failures within "
        "60 seconds, transition to OPEN and route requests to the "
        "secondary payment processor."
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence omitted observation window"
    )


def test_conflicting_timeout_threshold_still_rejected():
    valid, detail = validate(
        "After 5 consecutive HTTP 5xx or timeout failures within "
        "30 seconds, transition to OPEN and route requests to the "
        "secondary payment processor. timeout_threshold = 3"
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence invented a conflicting "
        "timeout threshold"
    )


def test_open_without_secondary_action_still_invalid():
    valid, detail = validate(
        "After 5 consecutive HTTP 5xx or timeout failures within "
        "30 seconds, transition from CLOSED to OPEN."
    )

    assert not valid
    assert detail == (
        "circuit-breaker evidence lacks state/fallback behavior"
    )
