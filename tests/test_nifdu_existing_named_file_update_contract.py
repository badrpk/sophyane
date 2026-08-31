from pathlib import Path

from sophyane.adaptive_execution import (
    _compact_repair_prompt,
)


RUNTIME_SOURCE = Path(
    "src/sophyane/runtime_intent_refinement_patch.py"
)

GUARDED_SOURCE = Path(
    "src/sophyane/nifdu_guarded_execution.py"
)


def _fast_path() -> str:
    text = RUNTIME_SOURCE.read_text(
        encoding="utf-8",
    )

    start = text.index(
        "SOPHYANE_NIFDU_GUARDED_FAST_PATH_V2"
    )

    end = text.index(
        "Planning with NIFDU; native Sophyane runtime",
        start,
    )

    return text[start:end]


def test_existing_named_python_file_hands_off_to_guarded_replace():
    section = _fast_path()

    assert (
        "SOPHYANE_NIFDU_EXISTING_NAMED_FILE_UPDATE_V1"
        in section
    )

    assert (
        "requested_python_filename("
        in section
    )

    assert (
        "execute_nifdu_file_continuation("
        in section
    )

    assert (
        "active_file=_nifdu_existing_target"
        in section
    )


def test_write_file_create_only_guard_remains_fail_closed():
    source = GUARDED_SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        "Fail closed instead of overwriting "
        "an unrelated existing file."
        in source
    )

    assert (
        'f"target already exists: {target.name}"'
        in source
    )

    assert (
        "def apply_file_replace_proposal("
        in source
    )


def test_native_nifdu_provider_must_return_action_not_result():
    source = RUNTIME_SOURCE.read_text(
        encoding="utf-8",
    )

    assert (
        "Return ONLY the next concrete executable Sophyane "
        in source
    )

    assert (
        "Do not return a completion/result envelope."
        in source
    )

    assert (
        "or completion response."
        not in source
    )


def test_guarded_result_distinguishes_update_from_create():
    section = _fast_path()

    assert (
        '"Updated and validated "'
        in section
    )

    assert (
        '"Created and validated "'
        in section
    )

    assert (
        "_nifdu_guarded_existing_update"
        in section
    )


def test_compact_repair_preserves_simple_original_semantics():
    original = (
        "make test.py that prints hello"
    )

    prompt = _compact_repair_prompt(
        original,
        ["test.py"],
        (
            '{"handled":true,"ok":true,'
            '"capability":'
            '"development.python_create_validate_run",'
            '"summary":"done","evidence":[]}'
        ),
    )

    lowered = prompt.casefold()

    assert original in prompt

    assert (
        "repair response serialization/schema only"
        in lowered
    )

    assert (
        "preserve the exact original task semantics"
        in lowered
    )

    assert (
        "result, not an executable action"
        in lowered
    )

    assert (
        "unless original task requests it"
        in lowered
    )
