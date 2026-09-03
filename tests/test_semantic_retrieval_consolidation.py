from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
import numpy as np

from sophyane.code_memory.store import (
    ChunkStore,
)

import sophyane.sli_semantic_intelligence as semantic


def _match_snapshot(matches):
    return [
        (
            match.chunk_id,
            round(
                float(
                    match.score
                ),
                12,
            ),
            match.capability,
            match.language,
            match.path,
            match.placement,
            match.source,
        )
        for match in matches
    ]


def test_retrieval_definitions_are_consolidated():
    path = Path(
        "src/sophyane/sli_semantic_intelligence.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        text
    )

    capability_nodes = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "retrieve_for_capability"
        )
    ]

    plan_nodes = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "retrieve_semantic_plan"
        )
    ]

    assert len(
        capability_nodes
    ) == 1

    assert len(
        plan_nodes
    ) == 1


def test_final_compatibility_policy_owns_retrieval():
    path = Path(
        "src/sophyane/sli_semantic_intelligence.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        text
    )

    node = next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "retrieve_for_capability"
        )
    )

    source = ast.get_source_segment(
        text,
        node,
    )

    assert source is not None

    assert (
        "_final_compatible"
        in source
    )

    # These belonged to the now-obsolete strict generation.
    assert "score += 2.0" not in source

    assert (
        "signal_count * 0.65"
        not in source
    )


def test_semantic_plan_delegates_to_capability_retrieval():
    path = Path(
        "src/sophyane/sli_semantic_intelligence.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        text
    )

    node = next(
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "retrieve_semantic_plan"
        )
    )

    source = ast.get_source_segment(
        text,
        node,
    )

    assert source is not None

    assert (
        "retrieve_for_capability("
        in source
    )

    # The compatibility implementation belongs in exactly one place.
    assert (
        "_final_compatible("
        not in source
    )


def test_direct_and_plan_retrieval_are_identical(
    tmp_path: Path,
    monkeypatch,
):
    state = (
        tmp_path
        / "state"
    )

    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(state),
    )

    store = ChunkStore()

    samples = (
        (
            (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                "@app.get('/health')\n"
                "def health():\n"
                "    return {'ok': True}\n"
            ),
            "python",
            "api.py",
            "api-source",
            [
                "python",
                "api",
            ],
        ),
        (
            (
                "import requests\n"
                "def fetch(url):\n"
                "    response = requests.get(url)\n"
                "    return response.json()\n"
            ),
            "python",
            "client.py",
            "client-source",
            [
                "python",
                "client",
            ],
        ),
        (
            (
                "<!doctype html>\n"
                "<html><body>"
                "<canvas id='game'></canvas>"
                "<script src='game.js'></script>"
                "</body></html>"
            ),
            "html",
            "index.html",
            "browser-source",
            [
                "html",
            ],
        ),
        (
            (
                "const canvas = "
                "document.querySelector('canvas');\n"
                "window.addEventListener("
                "'keydown', onKey);\n"
                "function render(){ "
                "requestAnimationFrame(render); }\n"
            ),
            "javascript",
            "game.js",
            "browser-source",
            [
                "javascript",
                "canvas",
            ],
        ),
        (
            (
                "body { display: grid; }\n"
                ".hero { font-size: 3rem; }\n"
            ),
            "css",
            "style.css",
            "style-source",
            [
                "css",
            ],
        ),
    )

    for (
        body,
        language,
        path,
        source,
        tags,
    ) in samples:
        store.add_chunk(
            body,
            language=language,
            path=path,
            source=source,
            tags=tags,
            weight=1.0,
            meta={},
        )

    store.flush()

    store = ChunkStore()

    request = (
        "Build a browser snake game "
        "using canvas and JavaScript."
    )

    direct_plan = semantic.build_semantic_plan(
        request
    )

    direct_output = {}

    for requirement in direct_plan.capabilities:
        direct_output[
            requirement.name
        ] = semantic.retrieve_for_capability(
            store,
            direct_plan,
            requirement,
            limit=6,
            minimum_score=0.75,
        )

    plan, output = (
        semantic.retrieve_semantic_plan(
            store,
            request,
            per_capability=6,
        )
    )

    assert [
        requirement.name
        for requirement
        in direct_plan.capabilities
    ] == [
        requirement.name
        for requirement
        in plan.capabilities
    ]

    assert set(
        direct_output
    ) == set(
        output
    )

    for capability in output:
        assert _match_snapshot(
            direct_output[
                capability
            ]
        ) == _match_snapshot(
            output[
                capability
            ]
        )


def test_final_browser_domain_filter_is_preserved(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_HOME",
        str(
            tmp_path
            / "state"
        ),
    )

    store = ChunkStore()

    store.add_chunk(
        (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "@app.get('/x')\n"
            "def x(): return {'x': 1}\n"
        ),
        language="python",
        path="backend.py",
        source="backend",
        tags=[
            "python",
            "api",
        ],
        weight=1.0,
        meta={},
    )

    store.add_chunk(
        (
            "<!doctype html>"
            "<html><body>"
            "<canvas id='game'></canvas>"
            "</body></html>"
        ),
        language="html",
        path="index.html",
        source="browser",
        tags=["html"],
        weight=1.0,
        meta={},
    )

    store.flush()

    plan, matches = (
        semantic.retrieve_semantic_plan(
            ChunkStore(),
            (
                "Build a browser snake game "
                "using canvas and JavaScript."
            ),
        )
    )

    assert (
        plan.target_artifact
        == "browser_application"
    )

    returned_languages = {
        match.language.casefold()
        for values in matches.values()
        for match in values
    }

    assert "python" not in returned_languages


def _ranking_chunk(chunk_id: str, *, provenance=None):
    return SimpleNamespace(
        id=chunk_id,
        text="evidence",
        language="python",
        path=f"{chunk_id}.py",
        source="test",
        tags=[],
        weight=1.0,
        meta=(
            {"verified_provenance": provenance}
            if provenance is not None
            else {}
        ),
    )


def _rank_with_scores(monkeypatch, chunks, scores, *, repository=None):
    plan = semantic.build_semantic_plan("repository engineering objective")
    requirement = SimpleNamespace(name="entry_point", query="objective")
    monkeypatch.setattr(semantic, "_final_compatible", lambda *args: True)
    monkeypatch.setattr(
        semantic,
        "_chunk_semantic_score",
        lambda chunk, _requirement, _plan: scores[chunk.id],
    )
    monkeypatch.setattr(semantic, "_repository_identity_for_query", lambda _query: repository)
    store = SimpleNamespace(chunks={chunk.id: chunk for chunk in chunks})
    return semantic.retrieve_for_capability(
        store,
        plan,
        requirement,
        limit=len(chunks),
        minimum_score=0.0,
    )


def _verified(repo="repo-alpha", accepted=True, state="verified"):
    return {
        "accepted": accepted,
        "verification_state": state,
        "repository_identity": repo,
        "objective_hash": "a" * 64,
    }


def test_verified_provenance_is_a_bounded_deterministic_tiebreak(monkeypatch):
    verified = _ranking_chunk("verified", provenance=_verified())
    legacy = _ranking_chunk("legacy")
    scores = {"verified": 1.0, "legacy": 1.0}
    first = _rank_with_scores(monkeypatch, [legacy, verified], scores)
    second = _rank_with_scores(monkeypatch, [legacy, verified], scores)
    assert [m.chunk_id for m in first] == ["verified", "legacy"]
    assert [(m.chunk_id, m.score) for m in first] == [(m.chunk_id, m.score) for m in second]
    assert first[0].score - first[1].score == pytest.approx(0.08)


def test_semantic_relevance_remains_primary_over_verified_bonus(monkeypatch):
    verified = _ranking_chunk("verified", provenance=_verified())
    ordinary = _ranking_chunk("ordinary")
    ranked = _rank_with_scores(
        monkeypatch,
        [verified, ordinary],
        {"verified": 0.9, "ordinary": 1.2},
    )
    assert [m.chunk_id for m in ranked] == ["ordinary", "verified"]


def test_matching_repository_gets_bounded_preference_without_filtering(monkeypatch):
    matching = _ranking_chunk("matching", provenance=_verified("repo-alpha"))
    other = _ranking_chunk("other", provenance=_verified("repo-beta"))
    ranked = _rank_with_scores(
        monkeypatch,
        [other, matching],
        {"matching": 1.0, "other": 1.0},
        repository="repo-alpha",
    )
    assert [m.chunk_id for m in ranked] == ["matching", "other"]
    only_other = _rank_with_scores(
        monkeypatch,
        [other],
        {"other": 1.0},
        repository="repo-alpha",
    )
    assert [m.chunk_id for m in only_other] == ["other"]


@pytest.mark.parametrize(
    "provenance",
    [
        {"accepted": False, "verification_state": "verified"},
        {"accepted": True, "verification_state": "failed"},
        {"accepted": True, "verification_state": "unverified"},
        {"accepted": "true", "verification_state": "verified"},
        {"accepted": True, "verification_state": None},
    ],
)
def test_noncanonical_provenance_is_neutral(monkeypatch, provenance):
    candidate = _ranking_chunk("candidate", provenance=provenance)
    legacy = _ranking_chunk("legacy")
    ranked = _rank_with_scores(
        monkeypatch,
        [candidate, legacy],
        {"candidate": 1.0, "legacy": 1.0},
    )
    assert [m.chunk_id for m in ranked] == ["candidate", "legacy"]
    assert ranked[0].score == ranked[1].score


def test_objective_hash_is_not_an_identity_filter_and_retrieval_is_read_only(monkeypatch):
    first = _ranking_chunk("first", provenance=_verified())
    second = _ranking_chunk("second", provenance={**_verified(), "objective_hash": "b" * 64})
    before = {c.id: dict(c.meta) for c in (first, second)}
    ranked = _rank_with_scores(monkeypatch, [first, second], {"first": 1.0, "second": 1.0})
    assert {m.chunk_id for m in ranked} == {"first", "second"}
    assert {c.id: c.meta for c in (first, second)} == before



def test_non_semantic_chunkstore_retrieval_uses_shared_provenance(monkeypatch):
    verified = _ranking_chunk("verified", provenance=_verified())
    legacy = _ranking_chunk("legacy")
    store = SimpleNamespace(
        ids=["legacy", "verified"],
        vectors=np.asarray([[1.0], [1.0]], dtype=np.float32),
        weights=np.asarray([1.0, 1.0], dtype=np.float32),
        chunks={"legacy": legacy, "verified": verified},
        embedder=SimpleNamespace(embed=lambda _query: [1.0]),
    )
    monkeypatch.setattr(
        "sophyane.code_memory.store._repository_identity_for_query",
        lambda _query: None,
    )
    ranked = ChunkStore.retrieve(store, "objective", top_k=2)
    assert [chunk.id for chunk, _score in ranked] == ["verified", "legacy"]


def test_semantic_and_non_semantic_order_agree(monkeypatch):
    verified = _ranking_chunk("verified", provenance=_verified())
    legacy = _ranking_chunk("legacy")
    store = SimpleNamespace(
        ids=["legacy", "verified"],
        vectors=np.asarray([[1.0], [1.0]], dtype=np.float32),
        weights=np.asarray([1.0, 1.0], dtype=np.float32),
        chunks={"legacy": legacy, "verified": verified},
        embedder=SimpleNamespace(embed=lambda _query: [1.0]),
    )
    monkeypatch.setattr(
        "sophyane.code_memory.store._repository_identity_for_query",
        lambda _query: None,
    )
    non_semantic = ChunkStore.retrieve(store, "objective", top_k=2)
    semantic_order = _rank_with_scores(
        monkeypatch,
        [legacy, verified],
        {"legacy": 1.0, "verified": 1.0},
    )
    assert [chunk.id for chunk, _score in non_semantic] == [m.chunk_id for m in semantic_order]


def test_recurrent_principle_prefers_scoped_candidate_without_double_count(monkeypatch, tmp_path):
    principle_path = tmp_path / ".sophyane-evolution" / "principles.json"
    principle_path.parent.mkdir(parents=True)
    principle_path.write_text(
        __import__("json").dumps({"version": 1, "principles": {
            "p1": {
                "id": "p1",
                "status": "recurrent",
                "origin": "verified_execution",
                "component": "entry_point",
                "capabilities": ["entry_point"],
                "repository_identity": "repo-alpha",
            }
        }}),
        encoding="utf-8",
    )
    aligned = _ranking_chunk("aligned")
    aligned.meta["capability_class"] = "entry_point"
    aligned.meta["repository_identity"] = "repo-alpha"
    other = _ranking_chunk("other")
    other.meta["capability_class"] = "entry_point"
    other.meta["repository_identity"] = "repo-beta"
    plan = semantic.build_semantic_plan("repository engineering objective")
    requirement = SimpleNamespace(name="entry_point", query="objective")
    monkeypatch.setattr(semantic, "_final_compatible", lambda *args: True)
    monkeypatch.setattr(semantic, "_chunk_semantic_score", lambda *_args: 1.0)
    monkeypatch.setattr(semantic, "_repository_identity_for_query", lambda _query: "repo-alpha")
    store = SimpleNamespace(chunks={"other": other, "aligned": aligned})
    ranked = semantic.retrieve_for_capability(
        store, plan, requirement, limit=2, minimum_score=0.0, principles_root=tmp_path
    )
    assert [match.chunk_id for match in ranked] == ["aligned", "other"]
    assert ranked[0].score - ranked[1].score == pytest.approx(0.02)


def test_recurrent_principle_is_neutral_for_legacy_candidate(monkeypatch, tmp_path):
    principle_path = tmp_path / ".sophyane-evolution" / "principles.json"
    principle_path.parent.mkdir(parents=True)
    principle_path.write_text(
        '{"version":1,"principles":{"p":{"id":"p","status":"recurrent",'
        '"origin":"verified_execution","component":"entry_point",'
        '"capabilities":["entry_point"]}}}', encoding="utf-8"
    )
    first = _ranking_chunk("first")
    second = _ranking_chunk("second")
    plan = semantic.build_semantic_plan("repository engineering objective")
    requirement = SimpleNamespace(name="entry_point", query="objective")
    monkeypatch.setattr(semantic, "_final_compatible", lambda *args: True)
    monkeypatch.setattr(semantic, "_chunk_semantic_score", lambda *_args: 1.0)
    monkeypatch.setattr(semantic, "_repository_identity_for_query", lambda _query: None)
    ranked = semantic.retrieve_for_capability(
        SimpleNamespace(chunks={"first": first, "second": second}),
        plan, requirement, limit=2, minimum_score=0.0, principles_root=tmp_path
    )
    assert [match.score for match in ranked] == [1.0, 1.0]
