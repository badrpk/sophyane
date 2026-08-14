from __future__ import annotations

import ast
from pathlib import Path

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
