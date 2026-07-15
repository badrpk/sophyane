from __future__ import annotations

from sophyane.budget import record_usage, reset_usage, status as budget_status
from sophyane.capabilities import capability_matrix
from sophyane.checkpoint import list_checkpoints, save_checkpoint
from sophyane.hitl import list_pending, request_approval, resolve
from sophyane.interpreter import run_python
from sophyane.mcp_bridge import call_tool, list_tools
from sophyane.observability import end_run, list_traces, start_run
from sophyane.permissions import get_profile, set_profile
from sophyane.rag import add_text, query
from sophyane.scheduler import list_jobs, schedule_job
from sophyane.skills import list_skills


def test_capability_matrix_coverage() -> None:
    m = capability_matrix()
    assert m["total"] >= 35
    assert m["ready"] >= 30
    assert m["coverage_pct"] >= 80


def test_skills_and_rag_repl() -> None:
    assert len(list_skills()) >= 5
    add_text("Federated PEFT adapters improve edge models.", source="test", title="peft")
    hits = query("PEFT adapters", top_k=3)
    assert hits["ok"] is True
    r = run_python("x = 2 + 2\nresult = x")
    assert r["ok"] is True


def test_mcp_budget_hitl_scheduler() -> None:
    tools = list_tools()
    assert len(tools["tools"]) >= 4
    assert call_tool("budget_status")["ok"] is True
    reset_usage()
    record_usage(tokens=10)
    assert budget_status()["tokens_used"] >= 10
    req = request_approval("test-action", "unit")
    rid = req["request"]["id"]
    assert resolve(rid, approve=True)["ok"] is True
    schedule_job("unit", "hello", every_sec=3600)
    assert list_jobs()["count"] >= 1


def test_permissions_checkpoint_traces() -> None:
    assert set_profile("workspace")["ok"] is True
    assert get_profile()["profile"] == "workspace"
    cp = save_checkpoint("unit", {"n": 1})
    assert cp["ok"] is True
    assert list_checkpoints()["count"] >= 1
    rid = start_run("unit")
    end_run(rid, ok=True)
    assert list_traces()["count"] >= 1
