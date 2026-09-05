import pytest

from sophyane.local_chunking import (
    decompose_request,
    merge_chunk_artifacts,
    parse_chunk_artifact,
)


def test_decompose_preserves_order_and_dependencies():
    chunks = decompose_request("- Build app\n- Add cart\n- Add checkout")
    assert [chunk.id for chunk in chunks] == ["task-1", "task-2", "task-3"]
    assert chunks[1].depends_on == ("task-1",)


def test_parse_rejects_workspace_escape():
    with pytest.raises(ValueError):
        parse_chunk_artifact('{"files":[{"path":"../bad.py","content":"x"}]}')


def test_merge_appends_and_rejects_conflicting_writes():
    result = merge_chunk_artifacts([
        {"files": [{"path": "a.txt", "content": "a"}]},
        {"files": [{"path": "a.txt", "operation": "append", "content": "b"}]},
    ])
    assert result["files"][0]["content"] == "ab"
    with pytest.raises(ValueError):
        merge_chunk_artifacts([
            {"files": [{"path": "a.txt", "content": "a"}]},
            {"files": [{"path": "a.txt", "content": "b"}]},
        ])
