from __future__ import annotations


def test_verified_episode_is_trusted_and_recalled(
    monkeypatch,
):
    import sophyane.episodic_memory as m

    records = {}

    def remember(
        content,
        *,
        namespace,
        memory_key=None,
        metadata=None,
    ):
        records[memory_key] = {
            "content": content,
            "namespace": namespace,
            "metadata": dict(
                metadata
                or {}
            ),
            "memory_key": memory_key,
            "source": "filesystem-journal",
        }

        return {
            "ok": True,
            "memory_key": memory_key,
            "backend": "filesystem-journal",
            "path": "/tmp/memory.jsonl",
        }

    def recall(
        query,
        *,
        namespace=None,
        limit=8,
    ):
        del query

        return [
            value
            for value in records.values()
            if (
                namespace is None
                or value["namespace"]
                == namespace
            )
        ][:limit]

    def status():
        return {
            "ok": True,
            "disk_first": True,
            "backend": "filesystem-journal",
        }

    monkeypatch.setattr(
        m,
        "_xerus_api",
        lambda: (
            remember,
            recall,
            status,
        ),
    )

    event = {
        "trace_id": "trace-verified",
        "objective_hash": "abc",
        "original_objective": (
            "improve verified episodic memory"
        ),
        "status": "succeeded",
        "accepted": True,
        "verification_state": "verified",
        "verification_evidence": [
            {
                "check": "pass",
            }
        ],
        "reward": 1.0,
        "provider_identity": "nifdu_browser",
        "model_identity": "chatgpt-browser",
        "session_mode": "nifdu_llm",
        "handled": True,
        "result": "verified result",
    }

    stored = (
        m.persist_execution_episode(
            event
        )
    )

    assert stored["ok"] is True
    assert stored["trusted"] is True
    assert (
        stored["authoritative"]
        is True
    )

    rows = m.recall_execution_episodes(
        "verified episodic memory",
        limit=4,
    )

    assert len(rows) == 1
    assert rows[0]["trusted"] is True
    assert (
        rows[0]["authoritative"]
        is True
    )
    assert (
        rows[0]["instruction_authority"]
        is False
    )


def test_failure_is_retained_but_never_authoritative(
    monkeypatch,
):
    import sophyane.episodic_memory as m

    rows = []

    def remember(
        content,
        *,
        namespace,
        memory_key=None,
        metadata=None,
    ):
        rows.append(
            {
                "content": content,
                "namespace": namespace,
                "metadata": metadata,
                "memory_key": memory_key,
                "source": "filesystem-journal",
            }
        )

        return {
            "ok": True,
            "memory_key": memory_key,
            "backend": "filesystem-journal",
        }

    def recall(
        query,
        *,
        namespace=None,
        limit=8,
    ):
        del query

        return [
            item
            for item in rows
            if item["namespace"]
            == namespace
        ][:limit]

    monkeypatch.setattr(
        m,
        "_xerus_api",
        lambda: (
            remember,
            recall,
            lambda: {
                "ok": True,
            },
        ),
    )

    stored = (
        m.persist_execution_episode(
            {
                "trace_id": "trace-failure",
                "original_objective": (
                    "failed approach"
                ),
                "status": "failed",
                "accepted": False,
                "verification_state": (
                    "unverified"
                ),
                "reward": -0.5,
                "handled": True,
            }
        )
    )

    assert stored["ok"] is True
    assert stored["trusted"] is False
    assert (
        stored["authoritative"]
        is False
    )

    recalled = (
        m.recall_execution_episodes(
            "failed approach"
        )
    )

    assert len(recalled) == 1
    assert (
        recalled[0]["trusted"]
        is False
    )
    assert (
        recalled[0][
            "instruction_authority"
        ]
        is False
    )

    assert (
        m.recall_execution_episodes(
            "failed approach",
            trusted_only=True,
        )
        == []
    )
