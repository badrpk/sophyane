from sophyane.sli_capability_engine import (
    is_preview_request,
)


def test_terminal_long_running_request_is_not_preview():
    request = (
        "Provide a terminal-access agent with explicit safety guardrails "
        "to monitor long-running background processes or daemon crash logs, "
        "dynamically diagnose out-of-memory or port-binding conflicts, "
        "and execute safe corrective shell scripts."
    )

    assert is_preview_request(request) is False


def test_long_running_process_is_not_preview():
    assert (
        is_preview_request(
            "monitor long-running background processes"
        )
        is False
    )


def test_unrelated_it_substring_is_not_preview_target():
    assert (
        is_preview_request(
            "run explicit diagnostics"
        )
        is False
    )


def test_real_preview_output_request_remains_preview():
    assert (
        is_preview_request(
            "run and preview the output"
        )
        is True
    )


def test_real_preview_project_request_remains_preview():
    assert (
        is_preview_request(
            "preview the project"
        )
        is True
    )


def test_real_open_result_request_remains_preview():
    assert (
        is_preview_request(
            "open the result"
        )
        is True
    )
