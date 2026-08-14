from __future__ import annotations

from dataclasses import dataclass

from sophyane.code_memory.store import CodeChunk
import sophyane.sli_semantic_intelligence as sem


REQUEST = (
    "Provide a terminal-access agent with explicit safety guardrails "
    "to monitor long-running background processes or daemon crash logs, "
    "dynamically diagnose out-of-memory or port-binding conflicts, "
    "and execute safe corrective shell scripts."
)

BAD = "hostile-graph-api"
GOOD = "real-log-diagnostics"
CAPABILITY = "log_diagnostics"


def _chunk(
    chunk_id: str,
    text: str,
    *,
    tags: list[str] | None = None,
    meta: dict | None = None,
) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        text=text,
        language="python",
        path=f"/app/{chunk_id}.py",
        license="unknown",
        source="deterministic-test-store",
        tags=list(tags or []),
        meta=dict(meta or {}),
        created_at=0.0,
        weight=1.0,
    )


BAD_CHUNK = _chunk(
    BAD,
    """
async def get_graph(repo_path=None, cypher_query=None):
    if not db_manager:
        raise HTTPException(
            status_code=500,
            detail="Database not initialized",
        )

    try:
        with db_manager.get_driver().session(
            **_read_session_kwargs(db_manager)
        ) as session:
            if cypher_query:
                if not _is_read_only_cypher(cypher_query):
                    raise HTTPException(
                        status_code=400,
                        detail="Only read-only queries are allowed",
                    )
                result = session.run(cypher_query)
            else:
                result = session.run(
                    "MATCH (n) RETURN n LIMIT 50000"
                )

        return {"nodes": list(result)}

    except HTTPException:
        raise
    except Exception as error:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )
""".strip(),
    tags=["python", "function", "get_graph"],
    meta={
        "domain": "http_api",
        "provides": [
            "directional_input",
            "error_handling",
            "progress_feedback",
            "rules_validation",
        ],
        "roles": [
            "directional_input",
            "progress_feedback",
            "rules_validation",
        ],
        "grounded_acquisition": True,
    },
)


GOOD_CHUNK = _chunk(
    GOOD,
    """
def inspect_log(path):
    text = path.read_text()
    tail = text.splitlines()[-100:]

    for line in tail:
        if "Traceback" in line:
            return line

    return None
""".strip(),
    tags=[
        "daemon",
        "logs",
        "tail",
        "traceback",
        "diagnostics",
    ],
    meta={
        "domain": "operations",
        "provides": ["log_diagnostics"],
        "roles": ["log_diagnostics"],
    },
)


@dataclass
class _Retrieved:
    chunk: CodeChunk
    score: float


class _DeterministicStore:
    """
    Minimal retrieval store for the public semantic-retrieval boundary.

    BAD is deliberately ranked above GOOD.  The admission layer must
    therefore reject BAD because semantic similarity/rank alone cannot
    establish the requested capability.
    """

    def __init__(self) -> None:
        self.chunks = {
            BAD: BAD_CHUNK,
            GOOD: GOOD_CHUNK,
        }

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ):
        ranked = [
            (self.chunks[BAD], 0.99),
            (self.chunks[GOOD], 0.90),
        ]
        return ranked[:top_k]


def _requirement(plan, name):
    return next(
        requirement
        for requirement in plan.capabilities
        if requirement.name == name
    )


def test_fixture_preserves_hostile_false_positive_boundary():
    assert not sem._strict_has_discriminative_evidence(
        BAD_CHUNK,
        CAPABILITY,
    )

    assert sem._strict_has_discriminative_evidence(
        GOOD_CHUNK,
        CAPABILITY,
    )


def test_live_retrieval_rejects_chunk_without_discriminative_evidence():
    store = _DeterministicStore()

    semantic_request, plan, matches = sem.enrich_with_semantics(
        REQUEST,
        store,
    )

    requirement = _requirement(
        plan,
        CAPABILITY,
    )

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
    assert GOOD in retrieved_ids


def test_enriched_semantic_matches_do_not_crown_strictly_rejected_chunk():
    store = _DeterministicStore()

    semantic_request, plan, matches = sem.enrich_with_semantics(
        REQUEST,
        store,
    )

    capability_matches = list(
        matches.get(CAPABILITY, [])
        or []
    )

    assert capability_matches

    assert all(
        match.chunk_id != BAD
        for match in capability_matches
    )

    assert any(
        match.chunk_id == GOOD
        for match in capability_matches
    )
