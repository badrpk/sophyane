from sophyane.code_memory.topic_site_compose import (
    extract_topic,
    is_topic_site_request,
)
from sophyane.runtime_sli_semantic import analyze


def test_topic_site_accepts_known_build_verb_typos() -> None:
    cases = {
        "make website on dogs": "dogs",
        "mske website on dogs": "dogs",
        "maek website on dogs": "dogs",
        "mak3 website on dogs": "dogs",
        "mkae website about steel": "steel",
        "create website about solar energy": "solar energy",
    }

    for request, topic in cases.items():
        assert extract_topic(request) == topic
        assert is_topic_site_request(request)


def test_build_verb_typos_use_shared_semantic_normalization() -> None:
    assert analyze(
        "mske website on dogs"
    ).normalized.lower().startswith("make website")

    assert analyze(
        "mkae website on dogs"
    ).normalized.lower().startswith("make website")


def test_non_build_requests_do_not_become_topic_sites() -> None:
    cases = (
        "tell me about dogs",
        "what is a website",
        "show information about dogs",
        "dog breeds",
    )

    for request in cases:
        assert not is_topic_site_request(request)


def test_interactive_products_remain_outside_topic_site_route() -> None:
    cases = (
        "make website calculator on electricity",
        "mske website game about dogs",
        "maek website dashboard about solar",
        "mkae website quiz about steel",
    )

    for request in cases:
        assert not is_topic_site_request(request)


def test_topic_extraction_preserves_original_subject() -> None:
    assert extract_topic(
        "mske website on german shepherd dogs"
    ) == "german shepherd dogs"

    assert extract_topic(
        "mkae website about induction furnaces"
    ) == "induction furnaces"
