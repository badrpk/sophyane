from __future__ import annotations


def test_discovery_xerus_memory_is_read_only_context(
    monkeypatch,
):
    import sophyane.episodic_memory as memory
    from sophyane.discovery_bridges import (
        _xerus_episodic_knowledge,
    )

    monkeypatch.setattr(
        memory,
        "recall_execution_episodes",
        lambda *args, **kwargs: [
            {
                "trace_id": "episode-1",
                "objective": "similar objective",
                "trusted": True,
                "authoritative": True,
                "reward": 1.0,
                "provider_identity": (
                    "nifdu_browser"
                ),
                "repository_identity": None,
                "instruction_authority": False,
            },
            {
                "trace_id": "episode-2",
                "objective": "failed attempt",
                "trusted": False,
                "authoritative": False,
                "reward": -0.5,
                "provider_identity": (
                    "nifdu_browser"
                ),
                "instruction_authority": False,
            },
        ],
    )

    records = (
        _xerus_episodic_knowledge(
            "similar objective",
            "/tmp/workspace",
        )
    )

    assert len(records) == 2

    trusted = records[0]
    negative = records[1]

    assert (
        trusted.kind
        == "verified_episodic_memory"
    )
    assert trusted.score == 1.0
    assert (
        trusted.metadata[
            "instruction_authority"
        ]
        is False
    )

    assert (
        negative.kind
        == "execution_experience"
    )
    assert negative.score <= 0.35
    assert (
        negative.metadata[
            "authoritative"
        ]
        is False
    )
