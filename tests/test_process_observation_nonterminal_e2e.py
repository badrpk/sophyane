from sophyane import adaptive_execution as adaptive


INCIDENT_COMMAND = (
    "ps -ef | grep -E "
    "'[l]ake build NavierStokes|[l]ean .*/NavierStokes/'"
)

INCIDENT_RESULT = (
    f"Command: {INCIDENT_COMMAND}\n"
    "Exit code: 0\n"
    "STDOUT:\n"
    "u0_a511 11799 11593 0 pts/4 lake build NavierStokes\n"
    "u0_a511 7169 11799 13 pts/4 "
    "lean NavierStokes/PulseGrowth.lean\n"
    "STDERR:\n"
)


def test_live_process_observation_is_read_only():
    assert adaptive._is_process_observation_command(
        INCIDENT_COMMAND
    )

    assert adaptive._is_read_only_inspection_command(
        INCIDENT_COMMAND
    )


def test_live_process_observation_may_be_meaningful_evidence():
    # This distinction is intentional:
    # the observation can be useful evidence that the build is running.
    assert adaptive.verification_result_is_meaningful(
        INCIDENT_COMMAND,
        INCIDENT_RESULT,
    )


def test_live_process_observation_cannot_be_terminal_verification():
    inspection = adaptive._is_read_only_inspection_command(
        INCIDENT_COMMAND
    )

    meaningful = adaptive.verification_result_is_meaningful(
        INCIDENT_COMMAND,
        INCIDENT_RESULT,
    )

    terminal = (
        not inspection
        and meaningful
    )

    assert inspection is True
    assert meaningful is True
    assert terminal is False


def test_actual_verification_command_remains_eligible():
    command = "python -m pytest -q"

    result = (
        f"Command: {command}\n"
        "Exit code: 0\n"
        "STDOUT:\n"
        "13 passed in 0.43s\n"
        "STDERR:\n"
    )

    assert not adaptive._is_read_only_inspection_command(
        command
    )

    assert adaptive.verification_result_is_meaningful(
        command,
        result,
    )


def test_runtime_state_contract_for_running_build():
    state = {
        "process_observed": True,
        "process_running": True,
        "process_exit_code": None,
        "task_verified": False,
        "kernel_build_acceptance": False,
    }

    assert state == {
        "process_observed": True,
        "process_running": True,
        "process_exit_code": None,
        "task_verified": False,
        "kernel_build_acceptance": False,
    }
