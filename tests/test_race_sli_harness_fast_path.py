from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.race_orchestrator import (
    make_sli_producer,
)


REQUEST = (
    "Repair the existing production code after a pytest "
    "test failure and re-run verification."
)


def _forbidden_sli_graph(*args, **kwargs):
    raise AssertionError(
        "run_sli_graph must not execute after "
        "race harness classification"
    )


def test_race_sli_harness_success_bypasses_sli_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    A harness-classified repair request must use the direct
    harness fast path.

    Even when the harness succeeds, the generic SLI graph must
    never execute afterward.
    """

    import sophyane.sli_graph as sli_graph
    import sophyane.sli_harness_orchestrator as harness

    calls = {
        "classify": 0,
        "harness": 0,
        "graph": 0,
    }

    def classify(_request):
        calls["classify"] += 1
        return True

    def run_harness(
        request,
        workspace,
        *,
        progress=None,
    ):
        calls["harness"] += 1

        assert request == REQUEST
        assert Path(workspace).exists()

        return {
            "ok": True,
            "success": True,
            "report": "deterministic harness success",
        }

    def forbidden_graph(*args, **kwargs):
        calls["graph"] += 1
        return _forbidden_sli_graph(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        harness,
        "is_harness_execution_request",
        classify,
    )

    monkeypatch.setattr(
        harness,
        "run_harness_execution",
        run_harness,
    )

    monkeypatch.setattr(
        sli_graph,
        "run_sli_graph",
        forbidden_graph,
    )

    producer = make_sli_producer(
        request=REQUEST,
        workspace=tmp_path,
    )

    proposal = producer()

    assert calls == {
        "classify": 1,
        "harness": 1,
        "graph": 0,
    }

    assert proposal.engine == "sli"
    assert proposal.payload[
        "route"
    ] == "harness_execution"

    assert proposal.payload[
        "success"
    ] is True

    assert (
        proposal.payload["report"]
        == "deterministic harness success"
    )

    assert proposal.requires_write is False


def test_race_sli_harness_failure_still_bypasses_sli_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    A failed local harness attempt must be returned as speculative
    evidence.

    It must NOT fall through into generic SLI graph acquisition,
    internet search, browser acquisition, or another SLI route.
    """

    import sophyane.sli_graph as sli_graph
    import sophyane.sli_harness_orchestrator as harness

    calls = {
        "classify": 0,
        "harness": 0,
        "graph": 0,
    }

    def classify(_request):
        calls["classify"] += 1
        return True

    def run_harness(
        request,
        workspace,
        *,
        progress=None,
    ):
        calls["harness"] += 1

        assert request == REQUEST
        assert Path(workspace).exists()

        return {
            "ok": False,
            "success": False,
            "error": "deterministic harness failure",
        }

    def forbidden_graph(*args, **kwargs):
        calls["graph"] += 1
        return _forbidden_sli_graph(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        harness,
        "is_harness_execution_request",
        classify,
    )

    monkeypatch.setattr(
        harness,
        "run_harness_execution",
        run_harness,
    )

    monkeypatch.setattr(
        sli_graph,
        "run_sli_graph",
        forbidden_graph,
    )

    producer = make_sli_producer(
        request=REQUEST,
        workspace=tmp_path,
    )

    proposal = producer()

    assert calls == {
        "classify": 1,
        "harness": 1,
        "graph": 0,
    }

    assert proposal.engine == "sli"
    assert proposal.payload[
        "route"
    ] == "harness_execution"

    assert proposal.payload[
        "success"
    ] is False

    assert (
        proposal.payload["report"]
        == "deterministic harness failure"
    )

    assert proposal.requires_write is False


def test_non_harness_request_retains_normal_sli_graph_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Protect the opposite branch as well: requests not classified
    for the coding harness must retain the ordinary SLI graph path.
    """

    import sophyane.sli_graph as sli_graph
    import sophyane.sli_harness_orchestrator as harness

    calls = {
        "classify": 0,
        "harness": 0,
        "graph": 0,
    }

    def classify(_request):
        calls["classify"] += 1
        return False

    def forbidden_harness(*args, **kwargs):
        calls["harness"] += 1
        raise AssertionError(
            "harness must not execute for "
            "non-harness request"
        )

    def fake_graph(
        request,
        *,
        workspace,
        progress=None,
        max_retries=1,
    ):
        calls["graph"] += 1

        assert request == "make a website about dogs"
        assert Path(workspace).exists()
        assert max_retries == 1

        return {
            "route": "acquisition",
            "success": True,
            "promoted": False,
            "report": "deterministic graph result",
        }

    monkeypatch.setattr(
        harness,
        "is_harness_execution_request",
        classify,
    )

    monkeypatch.setattr(
        harness,
        "run_harness_execution",
        forbidden_harness,
    )

    monkeypatch.setattr(
        sli_graph,
        "run_sli_graph",
        fake_graph,
    )

    producer = make_sli_producer(
        request="make a website about dogs",
        workspace=tmp_path,
    )

    proposal = producer()

    assert calls == {
        "classify": 1,
        "harness": 0,
        "graph": 1,
    }

    assert proposal.engine == "sli"
    assert proposal.payload[
        "route"
    ] == "acquisition"

    assert proposal.payload[
        "success"
    ] is True
