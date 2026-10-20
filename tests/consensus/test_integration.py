import json

from sophyane.consensus.engine import BFTConsensusEngine


BASE_COMMIT = "a" * 40


def test_end_to_end_bft_run_records_two_adversaries_without_workspace_mutation(tmp_path):
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    workers = ["model-a", "model-b", "model-c", "malicious-ast", "malicious-json"]
    honest_ast = "def score():\n    return 3\n"

    def payload(worker_id, ast=honest_ast):
        return json.dumps({
            "worker_id": worker_id,
            "decision": {"action": "keep", "score": 3},
            "ast": ast,
            "git_head": BASE_COMMIT,
        })

    calls = {
        "model-a": lambda _: payload("model-a"),
        "model-b": lambda _: payload("model-b"),
        "model-c": lambda _: payload("model-c"),
        "malicious-ast": lambda _: payload("malicious-ast", "def score(:\n return 3"),
        "malicious-json": lambda _: "not-json",
    }
    engine = BFTConsensusEngine(tmp_path / "consensus_ledger.sqlite3", workers)

    result = engine.decide({"task": "candidate"}, base_commit=BASE_COMMIT, worker_calls=calls)

    assert result.status == "finalized"
    assert set(result.isolated_workers) == {"malicious-ast", "malicious-json"}
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert {event["event_type"] for event in engine.ledger.events(result.round_id)} == {"quorum_reached"}
    rows = engine.ledger.votes(result.round_id)
    assert len(rows) == 5
    assert {row["failure_boundary"] for row in rows if row["status"] == "invalid"} == {"ast_contract", "json_schema"}
