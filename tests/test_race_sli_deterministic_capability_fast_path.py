from pathlib import Path

import sophyane.race_orchestrator as race_orchestrator


REQUEST = (
    "Create a file named event18.txt containing exactly: "
    "Sophyane event 18 learning verification"
)

EXPECTED = b"Sophyane event 18 learning verification"


def test_sli_race_uses_deterministic_capability_before_graph(
    tmp_path: Path,
    monkeypatch,
):
    """
    Deterministic filesystem capabilities must execute inside the
    isolated SLI shadow before the generic SLI graph is considered.

    The authoritative workspace must remain untouched while the
    speculative producer runs.
    """

    def forbidden_graph(*args, **kwargs):
        raise AssertionError(
            "run_sli_graph must not execute when the unified "
            "execution kernel handles the deterministic request"
        )

    import sophyane.sli_graph as sli_graph

    monkeypatch.setattr(
        sli_graph,
        "run_sli_graph",
        forbidden_graph,
    )

    shadow_registry = {}

    producer = race_orchestrator.make_sli_producer(
        request=REQUEST,
        workspace=tmp_path,
        shadow_registry=shadow_registry,
    )

    proposal = producer()

    # Speculative SLI work must never mutate the authoritative workspace.
    assert not (tmp_path / "event18.txt").exists()

    shadow = shadow_registry["sli"]

    assert shadow != tmp_path
    assert (shadow / "event18.txt").read_bytes() == EXPECTED

    assert proposal.engine == "sli"
    assert proposal.kind == "patch"

    payload = proposal.payload

    assert payload["success"] is True
    assert "event18.txt" in payload["changed_files"]


def test_existing_winner_action_promotes_deterministic_shadow_write(
    tmp_path: Path,
    monkeypatch,
):
    """
    A deterministic mutation performed in the SLI shadow must use the
    existing SLI shadow-promotion contract rather than an
    already-executed authoritative-workspace bypass.
    """

    def forbidden_graph(*args, **kwargs):
        raise AssertionError(
            "generic SLI graph unexpectedly executed"
        )

    import sophyane.sli_graph as sli_graph

    monkeypatch.setattr(
        sli_graph,
        "run_sli_graph",
        forbidden_graph,
    )

    shadow_registry = {}

    producer = race_orchestrator.make_sli_producer(
        request=REQUEST,
        workspace=tmp_path,
        shadow_registry=shadow_registry,
    )

    proposal = producer()

    class Winner:
        worker = "sli"
        value = proposal

    # Import privately here because this regression specifically proves
    # compatibility with the existing race finalization contract.
    from sophyane.race_execution import _winner_action

    action = _winner_action(Winner())

    assert action is not None

    # Accept the normalized action vocabulary used by race_execution.
    assert action.get("type") in {
        "write",
        "write_file",
    }

    assert action["path"] == "event18.txt"
    assert action["content"].encode("utf-8") == EXPECTED
