from pathlib import Path

from sophyane.capability_executors import (
    execute_deterministic_capability,
)


def test_exact_verified_write_bypasses_folder_classifier(
    tmp_path: Path,
) -> None:
    result = execute_deterministic_capability(
        "Using filesystem tools, create harness_verify.txt in the current "
        "workspace containing exactly HARNESS_OK with no newline. Read the "
        "file back, verify it byte-for-byte, and respond only VERIFIED.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "filesystem.write_exact_verified"
    assert result.text == "VERIFIED"
    assert (tmp_path / "harness_verify.txt").read_bytes() == b"HARNESS_OK"
    assert result.data["byte_for_byte_verified"] is True
    assert result.data["newline_added"] is False


def test_ordinary_folder_listing_is_unchanged(
    tmp_path: Path,
) -> None:
    (tmp_path / "alpha").mkdir()

    result = execute_deterministic_capability(
        "List the folders in the current workspace.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.capability_id == "filesystem.list_folders"
    assert result.data["folders"] == ["alpha"]


def test_non_exact_general_file_request_falls_through(
    tmp_path: Path,
) -> None:
    result = execute_deterministic_capability(
        "Create a detailed report file about the project.",
        workspace=tmp_path,
    )

    assert result is None


def test_compound_build_request_is_not_resurrected_as_folder_listing(
    tmp_path: Path,
) -> None:
    request = (
        "Build a complete production-style steel plant operations web "
        "application from scratch in a new folder named "
        "steel-plant-command-center. "
        "The application must have a Python backend, responsive browser "
        "frontend, persistent local database, REST API and automated tests. "
        "Include heats, billets, rebar production, equipment status, alarms, "
        "production scheduling and an energy optimizer. "
        "Build all required files autonomously. Run syntax checks and tests, "
        "start the application, verify the frontend and REST API, and open "
        "the verified application in the browser."
    )

    result = execute_deterministic_capability(
        request,
        workspace=tmp_path,
    )

    assert result is None


def test_v20_classifier_decline_is_authoritative_over_folder_heuristic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.runtime_filesystem_capabilities_v20 as filesystem_v20

    monkeypatch.setattr(
        filesystem_v20,
        "classify_request",
        lambda _request: None,
    )

    result = execute_deterministic_capability(
        "Build an application in a new folder and list its components.",
        workspace=tmp_path,
    )

    assert result is None


def test_folder_heuristic_remains_fallback_when_v20_classifier_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sophyane.runtime_filesystem_capabilities_v20 as filesystem_v20

    (tmp_path / "alpha").mkdir()

    def unavailable(_request):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(
        filesystem_v20,
        "classify_request",
        unavailable,
    )

    result = execute_deterministic_capability(
        "List the folders in the current workspace.",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "filesystem.list_folders"
    assert result.data["folders"] == ["alpha"]


def test_v20_recognizes_natural_list_the_folders_phrase() -> None:
    from sophyane.runtime_filesystem_capabilities_v20 import classify_request

    assert classify_request(
        "List the folders in the current workspace."
    ) == {"type": "filesystem.list_folders"}


def test_v20_project_request_with_folder_language_still_declines() -> None:
    from sophyane.runtime_filesystem_capabilities_v20 import classify_request

    assert classify_request(
        "Build an application in a new folder and list its components."
    ) is None


# SOPHYANE_EXACT_WRITE_WHOLE_MISSION_SCOPE_V1

def test_exact_write_does_not_claim_compound_browser_mission(tmp_path):
    from sophyane.capability_executors import (
        execute_deterministic_capability,
    )

    request = (
        "Create a new folder named hello-sophyane-test. "
        "Inside it create index.html with a simple webpage showing "
        'the heading "Hello Sophyane" and a button that says "Working". '
        "Open the page in the browser and verify it loads successfully."
    )

    result = execute_deterministic_capability(
        request,
        workspace=tmp_path,
    )

    assert result is None
    assert not (tmp_path / "index.html").exists()


def test_exact_write_does_not_claim_create_and_open_mission(tmp_path):
    from sophyane.capability_executors import (
        execute_deterministic_capability,
    )

    request = (
        "Create index.html with exactly: <h1>Hello</h1> "
        "and open it in the browser."
    )

    result = execute_deterministic_capability(
        request,
        workspace=tmp_path,
    )

    assert result is None
    assert not (tmp_path / "index.html").exists()


def test_exact_write_still_claims_single_action_exact_write(tmp_path):
    from sophyane.capability_executors import (
        execute_deterministic_capability,
    )

    result = execute_deterministic_capability(
        "Create index.html with exactly: <h1>Hello</h1>",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True
    assert result.capability_id == "filesystem.write_exact_verified"
    assert (tmp_path / "index.html").read_text(
        encoding="utf-8"
    ) == "<h1>Hello</h1>"
