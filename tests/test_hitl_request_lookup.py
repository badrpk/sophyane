from __future__ import annotations

import json
from pathlib import Path

import pytest

import sophyane.hitl as hitl


@pytest.fixture
def isolated_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    state = tmp_path / "hitl"
    queue = state / "queue.json"

    monkeypatch.setattr(
        hitl,
        "HITL_DIR",
        state,
    )
    monkeypatch.setattr(
        hitl,
        "QUEUE",
        queue,
    )

    return queue


def test_get_request_returns_exact_pending_entry_read_only(
    isolated_queue: Path,
) -> None:
    created = hitl.request_approval(
        "competitive_apply:digest",
        '{"approval_digest":"digest"}',
        risk="high",
    )
    request_id = created["request"]["id"]

    before = isolated_queue.read_bytes()
    found = hitl.get_request(request_id)
    after = isolated_queue.read_bytes()

    assert found["ok"] is True
    assert found["request"] == created["request"]
    assert found["request"]["status"] == "pending"
    assert before == after


def test_get_request_returns_resolved_entry(
    isolated_queue: Path,
) -> None:
    created = hitl.request_approval(
        "competitive_apply:digest",
        "bound payload",
        risk="high",
    )
    request_id = created["request"]["id"]

    resolved = hitl.resolve(
        request_id,
        approve=True,
        note="reviewed",
    )

    found = hitl.get_request(request_id)

    assert found["ok"] is True
    assert found["request"] == resolved["request"]
    assert found["request"]["status"] == "approved"
    assert found["request"]["note"] == "reviewed"


@pytest.mark.parametrize(
    "request_id",
    [
        "",
        " ",
        None,
        123,
        "missing",
    ],
)
def test_get_request_fails_closed_for_invalid_or_missing_id(
    isolated_queue: Path,
    request_id,
) -> None:
    result = hitl.get_request(request_id)

    assert result["ok"] is False
    assert "error" in result


def test_get_request_rejects_duplicate_id(
    isolated_queue: Path,
) -> None:
    isolated_queue.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    isolated_queue.write_text(
        json.dumps(
            [
                {
                    "id": "duplicate",
                    "status": "pending",
                },
                {
                    "id": "duplicate",
                    "status": "approved",
                },
            ]
        ),
        encoding="utf-8",
    )

    before = isolated_queue.read_bytes()
    result = hitl.get_request("duplicate")

    assert result == {
        "ok": False,
        "error": "duplicate request id",
    }
    assert isolated_queue.read_bytes() == before


def test_returned_request_is_not_a_live_queue_reference(
    isolated_queue: Path,
) -> None:
    created = hitl.request_approval(
        "competitive_apply:digest",
        "bound payload",
        risk="high",
    )
    request_id = created["request"]["id"]

    found = hitl.get_request(request_id)
    found["request"]["status"] = "tampered"

    reread = hitl.get_request(request_id)

    assert reread["request"]["status"] == "pending"


def test_get_request_source_contains_no_save_or_resolution_route() -> None:
    import inspect

    source = inspect.getsource(
        hitl.get_request
    )

    for forbidden in (
        "_save",
        "write_text",
        "resolve(",
        "unlink",
        "replace(",
    ):
        assert forbidden not in source
