from __future__ import annotations

from pathlib import Path

import sophyane.code_memory.acquire as acquire
import sophyane.code_memory.compose as compose


def test_composer_reports_workspace_relative_paths():
    source = Path(
        "src/sophyane/code_memory/compose.py"
    ).read_text(
        encoding="utf-8",
    )

    assert "p.relative_to(workspace)" in source

    # Old basename-only reporting caused:
    #
    #   main.cpp, ..., main.cpp
    #
    # for root/main.cpp and src/main.cpp.
    assert (
        "join(p.name for p in written)"
        not in source
    )


def test_batch_acquisition_measures_memory_after_flush():
    source = Path(
        "src/sophyane/code_memory/acquire.py"
    ).read_text(
        encoding="utf-8",
    )

    # Consolidated acquire_tree() performs batching directly.
    assert "store.begin_batch()" in source
    assert "store.end_batch()" in source

    # Durable memory is measured only after the batch has flushed.
    assert "durable_store = ChunkStore()" in source
    assert '"memory_size": len(' in source
    assert "durable_store.ids" in source

    # The historical wrapper/monkey-patch implementation is gone.
    assert "SOPHYANE_POST_FLUSH_MEMORY_REPORT_V1" not in source
    assert "_acquire_tree_before_batch" not in source
    assert "_BatchChunkStore" not in source
    assert "original_class().ids" not in source


def test_relative_reporting_distinguishes_public_and_source_main(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"

    public = (
        workspace
        / "main.cpp"
    )

    source = (
        workspace
        / "src"
        / "main.cpp"
    )

    public.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    public.write_text(
        "int main() { return 0; }\n",
        encoding="utf-8",
    )

    source.write_text(
        "int main() { return 0; }\n",
        encoding="utf-8",
    )

    reported = [
        str(
            path.relative_to(
                workspace
            )
        )
        for path in (
            public,
            source,
        )
    ]

    assert reported == [
        "main.cpp",
        "src/main.cpp",
    ]
