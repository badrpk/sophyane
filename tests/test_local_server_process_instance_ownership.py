from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(
    "src/sophyane/local_server.py"
)


def _source() -> str:
    return SOURCE.read_text(
        encoding="utf-8",
    )


def _functions():
    tree = ast.parse(
        _source(),
        filename=str(
            SOURCE
        ),
    )

    return {
        node.name: node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
    }


def test_process_instance_ownership_contract_exists():
    text = _source()

    for token in (
        "SOPHYANE_LLAMA_PROCESS_INSTANCE_OWNERSHIP_V1",
        "_process_start_ticks",
        "_ownership_file",
        "_write_ownership",
        "_read_ownership",
        "_owned_process_matches",
        '"launcher": "sophyane"',
        '"start_ticks"',
        '"boot_id"',
        '"model"',
        '"port"',
    ):
        assert token in text


def test_external_discovery_does_not_claim_ownership():
    functions = _functions()

    rendered = ast.unparse(
        functions[
            "_reconcile_server_pid"
        ]
    )

    assert (
        "_write_ownership"
        not in rendered
    )

    assert (
        "_write_pid(discovered_pid)"
        not in rendered
    )

    assert (
        "return discovered_pid"
        in rendered
    )


def test_automatic_termination_requires_instance_ownership():
    functions = _functions()

    rendered = ast.unparse(
        functions[
            "ensure_server_background"
        ]
    )

    check = rendered.index(
        "_owned_process_matches("
    )

    terminate = rendered.index(
        "_terminate_process_group(old_pid)"
    )

    assert check < terminate


def test_runtime_clear_removes_owner_record():
    functions = _functions()

    rendered = ast.unparse(
        functions[
            "_clear_runtime_state"
        ]
    )

    assert (
        "_ownership_file()"
        in rendered
    )


def test_launch_records_process_instance_ownership():
    functions = _functions()

    rendered = ast.unparse(
        functions[
            "_launch"
        ]
    )

    assert (
        "_write_ownership(process.pid, state, port)"
        in rendered
    )

    #
    # The old launch path must no longer establish ownership
    # using PID alone.
    #
    assert (
        "_write_pid(process.pid)"
        not in rendered
    )


def test_start_ticks_parser_uses_linux_starttime_field():
    functions = _functions()

    rendered = ast.unparse(
        functions[
            "_process_start_ticks"
        ]
    )

    assert (
        "fields[19]"
        in rendered
    )

    assert (
        "rfind(" in rendered
    )


def test_owned_process_requires_pid_boot_start_model_port():
    functions = _functions()

    rendered = ast.unparse(
        functions[
            "_owned_process_matches"
        ]
    )

    for token in (
        "owner_pid",
        "owner_start",
        "owner_port",
        "_boot_id()",
        "_expected_gguf",
        "_process_start_ticks",
        "_pid_matches_expected_server",
    ):
        assert token in rendered
