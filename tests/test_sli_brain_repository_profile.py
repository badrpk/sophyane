from sophyane.runtime_sli_brain import (
    _profile,
    _repository_coding_profile_request,
    decide,
)


def test_python_repository_mission_gets_coding_profile() -> None:
    request = (
        "Modify the Python source code and tests in the currently "
        "attached Sophyane repository. Inspect src/sophyane and tests, "
        "run pytest, and improve routing."
    )

    assert _repository_coding_profile_request(request)
    assert _profile(request) == "REPOSITORY_CODING"


def test_negated_html_and_website_terms_do_not_override_code() -> None:
    request = (
        "Modify src/sophyane and tests. This is not an HTML task. "
        "Do not create a website, preview, canvas or browser artifact. "
        "Run pytest after changing the Python source code."
    )

    decision = decide(
        request,
        has_project=True,
    )

    assert decision.profile == "REPOSITORY_CODING"
    assert decision.route == "continue_project"
    assert not any(
        "browser" in criterion.lower()
        or "http" in criterion.lower()
        for criterion in decision.criteria
    )


def test_actual_website_request_remains_web_standard() -> None:
    decision = decide(
        "Build a responsive website for a bakery",
        has_project=False,
    )

    assert decision.profile == "WEB_STANDARD"
    assert decision.route == "execution"
    assert any(
        "browser" in criterion.lower()
        or "http" in criterion.lower()
        for criterion in decision.criteria
    )


def test_repository_request_can_discuss_visual_bug() -> None:
    request = (
        "Fix the visual canvas routing bug in this repository. "
        "Patch src/sophyane and add regression tests under tests/."
    )

    assert _profile(request) == "REPOSITORY_CODING"
