import pytest

from sophyane.code_memory.store import ChunkStore
import sophyane.sli_semantic_intelligence as sem


REQUEST = (
    "Provide a terminal-access agent with explicit safety guardrails "
    "to monitor long-running background processes or daemon crash logs, "
    "dynamically diagnose out-of-memory or port-binding conflicts, "
    "and execute safe corrective shell scripts."
)

BAD = "f177e61258694d63"
CAPABILITY = "log_diagnostics"


def _requirement(plan, name):
    return next(
        requirement
        for requirement in plan.capabilities
        if requirement.name == name
    )


def test_live_retrieval_rejects_chunk_without_discriminative_evidence():
    store = ChunkStore()

    if BAD not in store.chunks:
        pytest.skip(
            "hostile live-corpus control chunk "
            f"{BAD} is not installed in this code-memory corpus"
        )

    bad = store.chunks[BAD]

    semantic_request, plan, matches = sem.enrich_with_semantics(
        REQUEST,
        store,
    )

    requirement = _requirement(
        plan,
        CAPABILITY,
    )

    # Corpus control: this is the exact false-positive demonstrated
    # by the hostile-corpus reproduction.
    assert not sem._strict_has_discriminative_evidence(
        bad,
        CAPABILITY,
    )

    # The public capability retrieval boundary must enforce the
    # strict admission policy. A chunk that cannot establish the
    # capability must not survive merely because its semantic score
    # is high.
    retrieved = sem.retrieve_for_capability(
        store,
        plan,
        requirement,
    )

    retrieved_ids = [
        match.chunk_id
        for match in retrieved
    ]

    assert BAD not in retrieved_ids


def test_enriched_semantic_matches_do_not_crown_strictly_rejected_chunk():
    store = ChunkStore()

    if BAD not in store.chunks:
        pytest.skip(
            "hostile live-corpus control chunk "
            f"{BAD} is not installed in this code-memory corpus"
        )

    bad = store.chunks[BAD]

    semantic_request, plan, matches = sem.enrich_with_semantics(
        REQUEST,
        store,
    )

    assert not sem._strict_has_discriminative_evidence(
        bad,
        CAPABILITY,
    )

    capability_matches = list(
        matches.get(CAPABILITY, [])
        or []
    )

    assert capability_matches

    # Stronger end-to-end contract: strict rejection must propagate
    # through the same semantic-enrichment path used by the engine.
    assert all(
        match.chunk_id != BAD
        for match in capability_matches
    )
