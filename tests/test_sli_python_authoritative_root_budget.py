from __future__ import annotations

from sophyane.code_memory.compose import (
    compose_python_from_chunks,
)
from sophyane.code_memory.store import CodeChunk


def chunk(
    chunk_id: str,
    *,
    function_name: str,
    payload_bytes: int,
) -> CodeChunk:
    # Build independently valid Python whose size can deterministically
    # exercise the aggregate assembly budget without relying on the
    # hostile corpus or any subject-specific capability.
    padding = "x" * payload_bytes

    source = (
        f"def {function_name}():\n"
        f"    payload = {padding!r}\n"
        f"    return len(payload)\n"
    )

    item = CodeChunk(
        id=chunk_id,
        text=source,
        language="python",
        path=f"/repo/{chunk_id}.py::{function_name}",
        source="test",
        weight=1.0,
    )

    item.meta = {
        "placement": "function",
        "provides": [chunk_id],
        "requires": [],
    }

    return item


def test_authoritative_roots_are_not_silently_lost_to_total_budget():
    # Each component is individually below the existing 16 KB component
    # ceiling, while their combined size exceeds the historical 32 KB
    # aggregate ceiling.
    roots = [
        chunk(
            "root_a",
            function_name="root_a",
            payload_bytes=8_000,
        ),
        chunk(
            "root_b",
            function_name="root_b",
            payload_bytes=8_000,
        ),
        chunk(
            "root_c",
            function_name="root_c",
            payload_bytes=8_000,
        ),
        chunk(
            "root_d",
            function_name="root_d",
            payload_bytes=8_000,
        ),
        chunk(
            "root_e",
            function_name="root_e",
            payload_bytes=2_000,
        ),
    ]

    for item in roots:
        # Establish that the input components themselves are valid.
        compile(
            item.text,
            f"<input:{item.id}>",
            "exec",
        )

    root_ids = [
        item.id
        for item in roots
    ]

    source, used = compose_python_from_chunks(
        roots,
        root_ids=root_ids,
    )

    compile(
        source,
        "<assembled>",
        "exec",
    )

    # root_ids is an authoritative semantic contract. Once all of these
    # independently valid components have been designated roots, the
    # assembler must not silently report successful partial composition
    # simply because earlier roots consumed a generic aggregate budget.
    assert used == root_ids

    for item in roots:
        assert item.id in used


def test_legacy_non_root_assembly_remains_bounded():
    chunks = [
        chunk(
            f"candidate_{index}",
            function_name=f"candidate_{index}",
            payload_bytes=8_000,
        )
        for index in range(5)
    ]

    source, used = compose_python_from_chunks(
        chunks,
    )

    compile(
        source,
        "<legacy-assembled>",
        "exec",
    )

    # This contract deliberately does NOT require legacy candidate
    # assembly to become unbounded. The stronger preservation contract
    # applies only when authoritative root_ids were explicitly supplied.
    assert used

    assert len(used) < len(chunks)

    assert len(
        source.encode("utf-8")
    ) <= 32_000
