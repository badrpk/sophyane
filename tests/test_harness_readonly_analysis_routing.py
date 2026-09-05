from sophyane.harness_task_policy import (
    is_execution_request,
    is_explicit_non_mutation_request,
)


ANALYSIS_REQUEST = (
    "Analyze the Sophyane repository and compare its current voice and "
    "audio capabilities with ElevenLabs. Identify the single highest-value "
    "missing capability that can be implemented safely. Give a concrete "
    "implementation plan with exact files, tests, dependencies, and "
    "acceptance criteria. Do not edit files."
)


def test_explicit_repository_analysis_without_edits_is_not_execution():
    assert is_explicit_non_mutation_request(ANALYSIS_REQUEST)
    assert is_execution_request(ANALYSIS_REQUEST) is False


def test_readonly_analysis_and_plan_only_are_not_execution():
    assert is_execution_request(
        "Perform a read-only analysis of this repository."
    ) is False
    assert is_execution_request(
        "Review the Python project and provide a plan only."
    ) is False


def test_genuine_software_execution_requests_remain_execution():
    assert is_execution_request(
        "Implement the fix in the Python repository and run tests."
    ) is True
    assert is_execution_request(
        "Analyze the repository performance bottleneck."
    ) is True


def test_scoped_edit_restriction_does_not_disable_execution():
    assert is_execution_request(
        "Fix the Python project but do not edit files outside src."
    ) is True


def test_explicit_read_file_action_remains_execution():
    assert is_execution_request(
        "Read the file config.py."
    ) is True
