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


def test_find_artifact_in_case_root(tmp_path: Path) -> None:
    from sophyane.evals.runner import _find_artifact

    target = tmp_path / "result.txt"
    target.write_text("ok", encoding="utf-8")

    assert _find_artifact(tmp_path, "result.txt") == target


def test_find_artifact_in_nested_sophyane_workspace(
    tmp_path: Path,
) -> None:
    from sophyane.evals.runner import _find_artifact

    target = tmp_path / ".sophyane-workspace" / "index.html"
    target.parent.mkdir()
    target.write_text("<html></html>", encoding="utf-8")

    assert _find_artifact(tmp_path, "index.html") == target


def test_find_artifact_preserves_relative_subdirectory(
    tmp_path: Path,
) -> None:
    from sophyane.evals.runner import _find_artifact

    target = (
        tmp_path
        / ".sophyane-workspace"
        / "config"
        / "settings.json"
    )
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")

    assert (
        _find_artifact(tmp_path, "config/settings.json")
        == target
    )


def test_evidence_corpus_reads_nested_json(
    tmp_path: Path,
) -> None:
    from sophyane.evals.runner import _evidence_corpus

    evidence = (
        tmp_path
        / ".sophyane-workspace"
        / ".sophyane-harness-report.json"
    )
    evidence.parent.mkdir()
    evidence.write_text(
        '{"exit_code": 7, "stdout": "STDOUT_OK"}',
        encoding="utf-8",
    )

    corpus = _evidence_corpus(tmp_path, "chat output")

    assert "chat output" in corpus
    assert '"exit_code": 7' in corpus
    assert "STDOUT_OK" in corpus
