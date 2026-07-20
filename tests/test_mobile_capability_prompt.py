from sophyane import adaptive_execution as adaptive
from sophyane.mobile_capability_prompt import COMPACT_CONTRACT, install_mobile_capability_prompt


def test_compact_prompt_keeps_full_mobile_contract(monkeypatch) -> None:
    original = adaptive._raw_html_prompt
    monkeypatch.setattr(adaptive, "_raw_html_prompt", lambda request, existing="": "GENERIC:" + request[-360:])
    install_mobile_capability_prompt()

    prompt = adaptive._raw_html_prompt(
        "make a mobile sensor dashboard with permission center, camera, microphone and GPS"
    )

    assert prompt == COMPACT_CONTRACT
    assert "Permission Center" in prompt
    assert "Location/GPS" in prompt
    assert "camera" in prompt
    assert "microphone" in prompt
    assert "session, 1 day, 7 days, 30 days or until revoked" in prompt
    assert prompt.startswith("Create ONE complete")
    monkeypatch.setattr(adaptive, "_raw_html_prompt", original)


def test_non_sensor_requests_keep_generic_prompt(monkeypatch) -> None:
    original = adaptive._raw_html_prompt
    monkeypatch.setattr(adaptive, "_raw_html_prompt", lambda request, existing="": "GENERIC:" + request)
    install_mobile_capability_prompt()

    assert adaptive._raw_html_prompt("make a chess game") == "GENERIC:make a chess game"
    monkeypatch.setattr(adaptive, "_raw_html_prompt", original)


def test_existing_mobile_project_keeps_edit_context(monkeypatch) -> None:
    original = adaptive._raw_html_prompt
    monkeypatch.setattr(adaptive, "_raw_html_prompt", lambda request, existing="": "GENERIC")
    install_mobile_capability_prompt()

    prompt = adaptive._raw_html_prompt("improve mobile phone sensor dashboard", "<html>old</html>")

    assert COMPACT_CONTRACT in prompt
    assert "EXISTING HTML" in prompt
    assert "<html>old</html>" in prompt
    monkeypatch.setattr(adaptive, "_raw_html_prompt", original)
