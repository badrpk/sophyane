from pathlib import Path

from sophyane.artifact_validation import validate_artifacts
from sophyane.repository_discovery import (
    discover_local_repositories,
    rank_repositories,
)
from sophyane.verification_contract import (
    Requirement,
    RequirementResult,
    build_report,
)


def test_artifact_validation_is_domain_agnostic(tmp_path: Path):
    good = tmp_path / "sample.py"
    good.write_text("value = 42\n")

    result = validate_artifacts(
        [good],
        workspace=tmp_path,
    )

    assert result.ok is True
    assert result.findings == ()


def test_artifact_validation_detects_syntax(tmp_path: Path):
    bad = tmp_path / "broken.py"
    bad.write_text("def broken(:\n    pass\n")

    result = validate_artifacts(
        [bad],
        workspace=tmp_path,
    )

    assert result.ok is False
    assert any(
        finding.code == "PYTHON_SYNTAX"
        for finding in result.findings
    )


def test_artifact_validation_denies_workspace_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside-universal-probe.txt"
    outside.write_text("probe")

    try:
        result = validate_artifacts(
            [outside],
            workspace=tmp_path,
        )

        assert result.ok is False
        assert any(
            finding.code == "WORKSPACE_ESCAPE"
            for finding in result.findings
        )
    finally:
        outside.unlink(missing_ok=True)


def test_verification_contract_requires_missing_checks():
    requirements = [
        Requirement(
            id="r1",
            description="requested behavior works",
        ),
        Requirement(
            id="r2",
            description="requested output exists",
        ),
    ]

    report = build_report(
        requirements,
        [
            RequirementResult(
                requirement_id="r1",
                satisfied=True,
                evidence="verified",
            )
        ],
    )

    assert report.ok is False
    assert "requirement was not verified" in report.problems


def test_repository_discovery_is_owner_driven():
    repos = discover_local_repositories()

    for _, _, owner, _ in repos:
        assert owner.lower() == "badrpk"


def test_repository_ranking_accepts_arbitrary_request_text():
    result = rank_repositories(
        "build and verify an arbitrary software task",
        limit=3,
    )

    assert isinstance(result, list)
    assert len(result) <= 3


def test_repository_discovery_deduplicates_logical_repositories():
    repos = discover_local_repositories()

    identities = [
        (owner.lower(), name.lower())
        for _, _, owner, name in repos
    ]

    assert len(identities) == len(set(identities))


def test_repository_ranking_ignores_generic_stop_words():
    from sophyane.repository_discovery import _tokens

    assert "and" not in _tokens("build and test application")
    assert "application" not in _tokens("build application")
    assert "persistence" in _tokens("add persistence")


def test_requirement_gate_rejects_unsatisfied_required_requirement():
    from sophyane.verification_contract import (
        VerificationFailure,
        require_verified,
    )

    report = build_report(
        [
            Requirement(
                id="required",
                description="required behavior",
            )
        ],
        [],
    )

    try:
        require_verified(report)
    except VerificationFailure:
        pass
    else:
        raise AssertionError("verification gate did not reject failure")


def test_universal_harness_module_is_domain_agnostic():
    import re
    from pathlib import Path

    path = Path("src/sophyane/universal_harness.py")
    text = path.read_text().lower()

    forbidden = (
        "snake",
        "tetris",
        "chess",
        "pong",
        "pacman",
        "dog",
        "cat",
        "calculator",
    )

    for token in forbidden:
        assert re.search(
            rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])",
            text,
        ) is None


def test_universal_harness_validates_workspace_artifact(tmp_path: Path):
    from sophyane.universal_harness import validate_task_artifacts

    artifact = tmp_path / "output.json"
    artifact.write_text('{"ok": true}\n')

    result = validate_task_artifacts(
        [artifact],
        workspace=tmp_path,
    )

    assert result.ok is True
