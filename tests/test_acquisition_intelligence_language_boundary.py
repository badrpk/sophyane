from __future__ import annotations

import sophyane.code_memory.acquisition_intelligence as intelligence


CPP_REQUEST = (
    "Implement a deterministic execution journal in C++ "
    "using std::vector std::thread std::mutex with replay "
    "of scheduling events."
)


def test_cpp_bypasses_browser_semantic_query_injection(
    monkeypatch,
) -> None:
    semantic_calls = []

    def fake_semantic_queries(
        request,
        maximum=10,
    ):
        semantic_calls.append(request)

        return [
            "wrong html javascript query",
            "wrong canvas javascript query",
        ]

    monkeypatch.setattr(
        intelligence,
        "semantic_queries",
        fake_semantic_queries,
    )

    namespace = {
        "_queries": lambda request: [
            "legacy C++ concurrency source",
        ],
        "build_search_queries": lambda request: [
            '"execution journal" C++ in:name,description,readme',
            "execution-journal cpp in:name,description,readme",
        ],
    }

    intelligence.install(
        namespace
    )

    result = namespace[
        "build_search_queries"
    ](
        CPP_REQUEST
    )

    joined = " ".join(
        result
    ).casefold()

    assert semantic_calls == []
    assert "c++" in joined or "cpp" in joined
    assert "javascript" not in joined
    assert "canvas" not in joined
    assert "html" not in joined


def test_cpp_private_and_public_query_paths_agree(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        intelligence,
        "semantic_queries",
        lambda *_args, **_kwargs: [
            "browser javascript contamination",
        ],
    )

    expected = [
        '"journal replay" C++ in:name,description,readme',
        "journal-replay cpp in:name,description,readme",
    ]

    namespace = {
        "_queries": lambda request: [
            "legacy fallback",
        ],
        "build_search_queries": lambda request: list(
            expected
        ),
    }

    intelligence.install(
        namespace
    )

    assert namespace["_queries"](
        CPP_REQUEST
    ) == expected

    assert namespace["build_search_queries"](
        CPP_REQUEST
    ) == expected


def test_browser_request_keeps_semantic_expansion(
    monkeypatch,
) -> None:
    semantic_calls = []

    def fake_semantic_queries(
        request,
        maximum=10,
    ):
        semantic_calls.append(request)

        return [
            "snake canvas javascript",
        ]

    monkeypatch.setattr(
        intelligence,
        "semantic_queries",
        fake_semantic_queries,
    )

    namespace = {
        "_queries": lambda request: [
            "snake source",
        ],
        "build_search_queries": lambda request: [
            "snake javascript html5",
        ],
    }

    request = (
        "Build a browser snake game using canvas "
        "and JavaScript."
    )

    intelligence.install(
        namespace
    )

    result = namespace[
        "build_search_queries"
    ](
        request
    )

    assert semantic_calls == [
        request
    ]

    joined = " ".join(
        result
    ).casefold()

    assert "canvas" in joined
    assert "javascript" in joined


def test_duplicate_queries_are_removed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        intelligence,
        "semantic_queries",
        lambda *_args, **_kwargs: [
            "same query",
            "same query",
        ],
    )

    namespace = {
        "_queries": lambda request: [
            "same query",
        ],
        "build_search_queries": lambda request: [
            "same query",
            "other query",
        ],
    }

    intelligence.install(
        namespace
    )

    result = namespace[
        "build_search_queries"
    ](
        "Build a browser application."
    )

    assert result == [
        "same query",
        "other query",
    ]
