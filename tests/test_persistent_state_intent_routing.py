from sophyane.runtime_sli_intent_patch import (
    persistent_state_inspection_request,
)


def test_explicit_local_state_inspection_executes() -> None:
    assert persistent_state_inspection_request(
        "Without re-injecting prior conversation history, read the local "
        "state file from our last turn and identify where the intermediate "
        "outputs are stored."
    )


def test_previous_run_log_inspection_executes() -> None:
    assert persistent_state_inspection_request(
        "Inspect the recent logs and checkpoint to find the conclusion "
        "of the previous run."
    )


def test_previous_task_storage_question_executes() -> None:
    assert persistent_state_inspection_request(
        "What was the previous task and where are its intermediate "
        "outputs stored?"
    )


def test_ordinary_persistence_question_remains_chat() -> None:
    assert not persistent_state_inspection_request(
        "What does persistence mean in software engineering?"
    )


def test_unrelated_previous_word_remains_chat() -> None:
    assert not persistent_state_inspection_request(
        "Compare this answer with the previous paragraph."
    )
