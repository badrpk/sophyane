from pathlib import Path


def _source() -> str:
    return Path(
        "src/sophyane/adaptive_execution.py"
    ).read_text(
        encoding="utf-8",
    )


def test_full_stack_pipeline_skips_pip_and_project_venv() -> None:
    source = _source()

    marker = "SOPHYANE_FULL_STACK_STDLIB_VERIFY_V1"

    assert marker in source

    start = source.index(
        marker
    )

    window = source[
        start:
        start + 9000
    ]

    assert "compileall -q" in window
    assert "-m pytest -q" in window
    assert "full_stack_fabric" in window

    full_stack_start = window.index(
        "if bundle_first_full_stack:"
    )

    full_stack_end = window.index(
        "            else:",
        full_stack_start,
    )

    branch = window[
        full_stack_start:
        full_stack_end
    ]

    assert "pip install" not in branch
    assert "-m venv .venv" not in branch

    fallback = window[
        full_stack_end:
        window.index(
            'elif deterministic_verification_stage == "full_stack_test":',
            full_stack_end,
        )
    ]

    assert "-m venv .venv" in fallback


def test_full_stack_pipeline_uses_service_fabric_not_custom_server() -> None:
    source = _source()

    assert (
        "SOPHYANE_FULL_STACK_SERVICE_FABRIC_CUTOVER_V1"
        in source
    )

    assert (
        "verify_full_stack_application"
        in source
    )

    assert (
        'deterministic_verification_stage == "full_stack_fabric"'
        in source
    )

    # Old parallel lifecycle ownership must be completely gone.
    assert ".sophyane-full-stack-server" not in source
    assert "FULL_STACK_HTTP_API_VERIFIED" not in source
    assert 'full_stack_launch"' not in source
    assert 'full_stack_api"' not in source

    # Runtime location is now discovered rather than hard-coded.
    assert (
        "http://127.0.0.1:8080/api/projects"
        not in source
    )

    assert (
        "http://127.0.0.1:8080/api/tasks"
        not in source
    )

    assert (
        "http://127.0.0.1:8080/api/stats"
        not in source
    )


def test_full_stack_pipeline_has_terminal_fabric_success() -> None:
    source = _source()

    assert (
        "Full-stack deterministic verification passed"
        in source
    )

    assert (
        "Service Fabric lifecycle"
        in source
    )

    assert (
        "grounded REST API"
        in source
    )


def test_service_fabric_cleanup_is_finally_guarded() -> None:
    source = Path(
        "src/sophyane/full_stack_verification.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "def verify_full_stack_application("
        in source
    )

    assert "finally:" in source
    assert "supervisor.stop_all()" in source
