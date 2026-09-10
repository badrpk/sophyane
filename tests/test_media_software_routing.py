from sophyane.tui_v2 import (
    _execution_requested,
    _pure_media_request,
)


RICH_SITE = (
    "make a premium modern dogs website with "
    "professional dog photography, strong visual hierarchy, "
    "polished responsive design, breed discovery, care guides "
    "and adoption sections"
)


def test_standalone_photography_remains_media():
    request = "create professional dog photography"

    assert _pure_media_request(request)
    assert not _execution_requested(request)


def test_photography_inside_website_is_not_pure_media():
    assert not _pure_media_request(RICH_SITE)


def test_photography_inside_website_routes_to_execution():
    assert _execution_requested(RICH_SITE)


def test_simple_website_creation_routes_to_execution():
    assert _execution_requested(
        "make dogs website"
    )


def test_informational_website_question_remains_chat():
    assert not _execution_requested(
        "what is a responsive website"
    )
