from sophyane import runtime_capability_acquisition_patch as capability
from sophyane.runtime_software_routing_guard import (
    _is_software_project,
    install_software_routing_guard,
)


def test_browser_game_is_software_project() -> None:
    request = (
        "Make a complete polished browser Snake game in one self-contained "
        "index.html and verify it over HTTP before completion."
    )
    assert _is_software_project(request)


def test_visual_poster_is_not_software_project() -> None:
    assert not _is_software_project("Make an editable birthday poster design")


def test_guard_blocks_canvas_route_for_browser_game(monkeypatch) -> None:
    monkeypatch.setattr(
        capability,
        "_is_editable_session_request",
        lambda _message: True,
    )
    install_software_routing_guard()

    assert not capability._is_editable_session_request(
        "Build a polished browser game in index.html"
    )
    assert capability._is_editable_session_request(
        "Make an editable portrait poster"
    )
