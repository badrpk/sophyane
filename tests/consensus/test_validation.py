import json

from sophyane.consensus.models import InvalidVote, ValidatedVote
from sophyane.consensus.validation import canonical_decision, validate_worker_response


BASE_COMMIT = "a" * 40


def valid_payload(worker_id: str = "worker-1", *, git_head: str = BASE_COMMIT) -> dict:
    return {
        "worker_id": worker_id,
        "decision": {"action": "keep", "score": 3},
        "ast": "def score():\n    return 3\n",
        "git_head": git_head,
    }


def test_valid_response_is_canonicalized_and_hashed():
    result = validate_worker_response(json.dumps(valid_payload()), base_commit=BASE_COMMIT)

    assert isinstance(result, ValidatedVote)
    assert result.worker_id == "worker-1"
    assert result.decision == {"action": "keep", "score": 3}
    assert len(result.digest) == 64
    assert result.failure_boundary is None


def test_duplicate_json_keys_are_rejected_at_json_boundary():
    raw = '{"worker_id":"worker-1","worker_id":"worker-2","decision":{},"ast":"x=1","git_head":"' + BASE_COMMIT + '"}'

    result = validate_worker_response(raw, base_commit=BASE_COMMIT)

    assert isinstance(result, InvalidVote)
    assert result.failure_boundary == "json_schema"


def test_corrupted_ast_is_rejected_at_ast_boundary():
    payload = valid_payload()
    payload["ast"] = "def score(:\n    return 3\n"

    result = validate_worker_response(payload, base_commit=BASE_COMMIT)

    assert isinstance(result, InvalidVote)
    assert result.failure_boundary == "ast_contract"


def test_ast_without_required_function_is_rejected_at_ast_contract_boundary():
    payload = valid_payload()
    payload["ast"] = "value = 3\n"

    result = validate_worker_response(payload, base_commit=BASE_COMMIT)

    assert isinstance(result, InvalidVote)
    assert result.failure_boundary == "ast_contract"


def test_divergent_git_head_is_rejected_at_git_boundary():
    payload = valid_payload(git_head="b" * 40)

    result = validate_worker_response(payload, base_commit=BASE_COMMIT)

    assert isinstance(result, InvalidVote)
    assert result.failure_boundary == "git_head"


def test_canonical_decision_is_order_independent():
    first = canonical_decision({"score": 3, "action": "keep"})
    second = canonical_decision({"action": "keep", "score": 3})

    assert first == second
