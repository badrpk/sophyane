from pathlib import Path

from sophyane.evals.runner import (
    EvalCase,
    _failure_class,
    _fraction,
    _routes,
    load_cases,
)


def test_fraction() -> None:
    assert _fraction([]) == 1.0
    assert _fraction([True, False]) == 0.5


def test_routes() -> None:
    output = (
        "SLI-graph route: topic_site\n"
        '{"capability": "validation.judge"}'
    )

    assert _routes(output) == [
        "topic_site",
        "validation.judge",
    ]


def test_infrastructure_classification() -> None:
    assert _failure_class(
        "HTTP 429 RESOURCE_EXHAUSTED quota exceeded",
        False,
        False,
        True,
    ) == "INFRASTRUCTURE"


def test_eval_cases_load() -> None:
    cases = load_cases(Path("evals/cases.jsonl"))

    assert cases
    assert len({case.id for case in cases}) == len(cases)
    assert any(case.critical for case in cases)


def test_case_schema() -> None:
    case = EvalCase.from_dict(
        {
            "id": "a",
            "prompt": "test",
            "unknown_future_field": "ignored",
        }
    )

    assert case.id == "a"


def test_unobservable_path_is_not_agent_routing_failure() -> None:
    assert _failure_class(
        "VERIFIED",
        True,
        False,
        True,
    ) == "EVALUATOR_OBSERVABILITY"
