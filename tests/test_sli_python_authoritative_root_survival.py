from __future__ import annotations

from sophyane.code_memory.compose import (
    compose_python_from_chunks,
)
from sophyane.code_memory.store import CodeChunk


def chunk(
    chunk_id: str,
    text: str,
    *,
    requires=(),
    provides=(),
    path: str | None = None,
) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        text=text,
        language="python",
        path=path or f"/repo/{chunk_id}.py",
        meta={
            "placement": "function",
            "requires": list(requires),
            "provides": list(provides),
        },
    )


def test_all_independent_authoritative_roots_survive_python_assembly():
    process = chunk(
        "root-process",
        (
            "def supervise_process(pid: int) -> bool:\n"
            "    return pid > 0\n"
        ),
        provides=("process_supervision",),
    )

    command = chunk(
        "root-command",
        (
            "def safe_command(argv):\n"
            "    return list(argv)\n"
        ),
        provides=("safe_command_execution",),
    )

    diagnostics = chunk(
        "root-diagnostics",
        (
            "def diagnose_resource(value):\n"
            "    return {'value': value}\n"
        ),
        provides=("resource_diagnostics",),
    )

    chunks = [
        process,
        command,
        diagnostics,
    ]

    roots = [
        process.id,
        command.id,
        diagnostics.id,
    ]

    source, used = compose_python_from_chunks(
        chunks,
        root_ids=roots,
    )

    compile(
        source,
        "<authoritative-root-survival>",
        "exec",
    )

    assert used == roots

    for root_id in roots:
        assert root_id in used


def test_authoritative_root_order_does_not_change_survival():
    roots_by_id = {
        "root-a": chunk(
            "root-a",
            (
                "def capability_a():\n"
                "    return 'a'\n"
            ),
            provides=("capability_a",),
        ),
        "root-b": chunk(
            "root-b",
            (
                "def capability_b():\n"
                "    return 'b'\n"
            ),
            provides=("capability_b",),
        ),
        "root-c": chunk(
            "root-c",
            (
                "def capability_c():\n"
                "    return 'c'\n"
            ),
            provides=("capability_c",),
        ),
    }

    incoming_orders = (
        ["root-a", "root-b", "root-c"],
        ["root-c", "root-b", "root-a"],
        ["root-b", "root-a", "root-c"],
    )

    expected = set(roots_by_id)

    for order in incoming_orders:
        chunks = [
            roots_by_id[root_id]
            for root_id in order
        ]

        source, used = compose_python_from_chunks(
            chunks,
            root_ids=list(expected),
        )

        compile(
            source,
            "<authoritative-root-order>",
            "exec",
        )

        assert set(used) == expected


def test_required_dependency_survives_with_authoritative_root():
    helper = chunk(
        "helper",
        (
            "def helper():\n"
            "    return 42\n"
        ),
        provides=("helper_service",),
    )

    root = chunk(
        "root",
        (
            "def root():\n"
            "    return helper()\n"
        ),
        requires=("helper_service",),
        provides=("root_service",),
    )

    noise = chunk(
        "noise",
        (
            "def unrelated_billing():\n"
            "    return 999\n"
        ),
        provides=("billing",),
    )

    source, used = compose_python_from_chunks(
        [root, helper, noise],
        root_ids=["root"],
    )

    compile(
        source,
        "<authoritative-root-dependency>",
        "exec",
    )

    assert "root" in used
    assert "helper" in used
    assert "noise" not in used
