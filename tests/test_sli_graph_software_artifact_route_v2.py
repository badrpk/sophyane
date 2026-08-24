from pathlib import Path

import pytest

from sophyane.sli_graph import (
    SLIState,
    _is_software_artifact_request,
    classify,
)


SOFTWARE_CASES = (
    (
        "Provide a terminal-access agent with explicit safety guardrails "
        "to monitor long-running background processes or daemon crash "
        "logs, dynamically diagnose out-of-memory or port-binding "
        "conflicts, and execute safe corrective shell scripts."
    ),
    (
        "Build a terminal agent that monitors daemon processes "
        "and executes corrective shell scripts."
    ),
    "Create a daemon monitoring tool that diagnoses crashes.",
    "Implement a shell automation tool for process monitoring.",
    (
        "Develop an operations agent that monitors services and "
        "repairs port conflicts."
    ),
    "Create a Python CLI for monitoring background processes.",
    "Build a REST API and client SDK.",
)

NON_SOFTWARE_CASES = (
    "Build a browser app for monitoring servers.",
    "Create a web app for monitoring daemon health.",
    "Explain how daemon process monitoring works.",
    "What is a terminal agent?",
    "Describe shell automation.",
)


@pytest.mark.parametrize("case", SOFTWARE_CASES)
def test_software_artifact_predicate_positive(
    case: str,
) -> None:
    assert _is_software_artifact_request(case)


@pytest.mark.parametrize("case", NON_SOFTWARE_CASES)
def test_software_artifact_predicate_negative(
    case: str,
) -> None:
    assert not _is_software_artifact_request(case)


@pytest.mark.parametrize("case", SOFTWARE_CASES)
def test_constructive_non_browser_software_routes_without_internet(
    case: str,
    tmp_path: Path,
) -> None:
    state = SLIState(
        request=case,
        workspace=str(tmp_path),
    )

    result = classify(
        state,
        lambda *_: None,
    )

    assert result.route == "software_artifact"


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        (
            "Build a browser app for monitoring servers.",
            "product_app",
        ),
        (
            "Create a web app for monitoring daemon health.",
            "product_app",
        ),
        (
            "Explain how daemon process monitoring works.",
            "general_knowledge",
        ),
        (
            "What is a terminal agent?",
            "general_knowledge",
        ),
    ),
)
def test_software_v2_preserves_other_route_families(
    case: str,
    expected: str,
    tmp_path: Path,
) -> None:
    state = SLIState(
        request=case,
        workspace=str(tmp_path),
    )

    result = classify(
        state,
        lambda *_: None,
    )

    assert result.route == expected
