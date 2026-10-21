import json

from sophyane.core_controller.audit import AuditStore
from sophyane.core_controller.models import AuditEvent, ModeName


def event(trace_id="trace-1", event_type="mode_selected", data=None):
    return AuditEvent(
        trace_id=trace_id,
        event_type=event_type,
        mode=ModeName.LOCAL_LLM,
        disposition="running",
        data=data or {},
    )


def test_audit_store_appends_jsonl_records_and_filters_by_trace(tmp_path):
    store = AuditStore(tmp_path / "audit.jsonl")
    store.append(event("one"))
    store.append(event("two", "terminal_failure"))

    records = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(records) == 2
    assert json.loads(records[0])["trace_id"] == "one"
    assert [item.trace_id for item in store.read("one")] == ["one"]


def test_audit_store_bounds_errors_and_redacts_secrets(tmp_path):
    store = AuditStore(tmp_path / "audit.jsonl")
    store.append(event(data={"api_key": "secret", "nested": {"password": "hidden", "error": "x" * 5000}}))

    raw = (tmp_path / "audit.jsonl").read_text()
    assert "secret" not in raw
    assert "hidden" not in raw
    assert len(json.loads(raw)["data"]["nested"]["error"]) <= 1000


def test_recover_inflight_marks_unknown_trace_without_promoting_it(tmp_path):
    store = AuditStore(tmp_path / "audit.jsonl")
    store.append(event("unfinished", "mode_selected"))
    store.append(event("finished", "mode_selected"))
    store.append(event("finished", "execution_completed", {"verification": "verified"}))

    assert store.recover_inflight() == ("unfinished",)
    recovered = store.read("unfinished")
    assert recovered[-1].event_type == "recovery_required"
    assert recovered[-1].disposition == "needs_review"


def test_read_ignores_truncated_or_malformed_trailing_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path)
    store.append(event())
    with path.open("a") as handle:
        handle.write('{"trace_id":"broken"')
        handle.write("not-json\n")

    assert len(store.read("trace-1")) == 1
