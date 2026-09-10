from __future__ import annotations

import json
from pathlib import Path

from sophyane.live_coding_doer import (
    LiveProgressReporter,
)
from sophyane.memory import MemoryStore
from sophyane.strict_interactive_doer import (
    StrictInteractiveCodingDoerRuntime,
)


def _runtime(
    tmp_path: Path,
    backend,
) -> StrictInteractiveCodingDoerRuntime:
    return StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=MemoryStore(
            tmp_path / "memory.db"
        ),
        workspace=tmp_path,
        max_steps=1,
        protocol_attempts=1,
        progress=LiveProgressReporter(
            heartbeat_seconds=60,
        ),
    )


def _plan(
    runtime: StrictInteractiveCodingDoerRuntime,
    prompt: str,
):
    return runtime._plan(
        prompt,
        "",
        prompt,
        [],
        [],
        "",
    )


def test_exact_single_file_planner_failure_does_not_call_artifact_fallback(
    tmp_path: Path,
) -> None:
    calls = 0

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        nonlocal calls
        calls += 1

        if calls == 1:
            raise TimeoutError(
                "planner timed out"
            )

        raise AssertionError(
            "artifact fallback must not be called"
        )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    prompt = (
        "Create exactly one file:\n\n"
        "research/dependency_graph.md\n\n"
        "Success means only that "
        "research/dependency_graph.md "
        "is created and is nonempty."
    )

    try:
        _plan(
            runtime,
            prompt,
        )
    except Exception as error:
        assert (
            type(error).__name__
            == "ProtocolError"
        )

        assert (
            "exact single-file"
            in str(error).lower()
        )
    else:
        raise AssertionError(
            "exact single-file planner "
            "failure did not fail closed"
        )

    assert calls == 1


def test_general_request_still_uses_artifact_fallback(
    tmp_path: Path,
) -> None:
    calls = 0

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        nonlocal calls
        calls += 1

        if calls == 1:
            raise TimeoutError(
                "planner timed out"
            )

        return json.dumps(
            {
                "objective":
                    "Create two files",
                "success_criteria": [
                    "a.txt exists",
                    "b.txt exists",
                ],
                "files": [
                    {
                        "path": "a.txt",
                        "content": "a\n",
                    },
                    {
                        "path": "b.txt",
                        "content": "b\n",
                    },
                ],
                "summary":
                    "bounded fallback bundle",
            }
        )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    plan = _plan(
        runtime,
        "Create a.txt and b.txt",
    )

    assert calls == 2

    assert (
        plan["action"]["type"]
        == "batch"
    )

    assert [
        action["path"]
        for action
        in plan["action"]["actions"]
    ] == [
        "a.txt",
        "b.txt",
    ]


def test_ambiguous_filename_mention_does_not_gain_exact_contract(
    tmp_path: Path,
) -> None:
    calls = 0

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        nonlocal calls
        calls += 1

        if calls == 1:
            raise TimeoutError(
                "planner timed out"
            )

        return json.dumps(
            {
                "objective":
                    "Create referenced file",
                "files": [
                    {
                        "path":
                            "research/example.md",
                        "content":
                            "fallback\n",
                    }
                ],
                "summary":
                    "generic fallback",
            }
        )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    plan = _plan(
        runtime,
        (
            "Please consider "
            "research/example.md "
            "and produce the requested artifact."
        ),
    )

    assert calls == 2

    assert (
        plan["action"]["type"]
        == "write_file"
    )


def test_valid_nested_exact_contract_is_recognized(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        lambda prompt, system: "",
    )

    assert (
        runtime
        ._explicit_single_file_contract_path(
            "Create exactly one file:\n\n"
            "research/maps/graph.md"
        )
        == "research/maps/graph.md"
    )


def test_exact_contract_path_escape_is_rejected(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        lambda prompt, system: "",
    )

    assert (
        runtime
        ._explicit_single_file_contract_path(
            "Create exactly one file:\n\n"
            "../outside.md"
        )
        is None
    )


def test_absolute_exact_contract_is_rejected(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        lambda prompt, system: "",
    )

    assert (
        runtime
        ._explicit_single_file_contract_path(
            "Create exactly one file:\n\n"
            "/tmp/outside.md"
        )
        is None
    )
