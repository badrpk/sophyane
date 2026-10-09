from sophyane.human_conversation_cli import (
    _continue_execution_request,
)


def test_run_only_instruction_does_not_inherit_prior_creation():
    original = (
        "Create training_workspace/hello_sophyane.py "
        "that prints Hello from Sophyane!"
    )

    followup = (
        "Execute the existing file "
        "training_workspace/hello_sophyane.py using Python. "
        "Do not write or modify files. "
        "Report the command, exit code, stdout and stderr."
    )

    combined = _continue_execution_request(
        followup,
        active_request=original,
    )

    assert combined == followup


def test_genuine_followup_retains_active_task_context():
    original = (
        "Build a calculator in calculator.py."
    )

    followup = (
        "Also add a subtraction function."
    )

    combined = _continue_execution_request(
        followup,
        active_request=original,
    )

    assert original in combined
    assert followup in combined
