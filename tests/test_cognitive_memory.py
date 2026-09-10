import json


def _episode(
    token: str,
):
    noise = " ".join(
        f"irrelevant_raw_detail_{i}"
        for i in range(250)
    )

    return {
        "trace_id": (
            "cognitive-test-trace"
            + token[-8:]
        ),
        "event_key": (
            "cognitive-test-event"
            + token[-8:]
        ),
        "original_objective": (
            "Remember the important verified marker "
            + token
            + ". Sparse recall should preserve the "
            "important lesson while forgetting most "
            "irrelevant details."
        ),
        "status": "succeeded",
        "accepted": True,
        "verification_state": "verified",
        "verification_evidence": [
            {
                "validator": "unit-test",
                "passed": True,
                "detail": (
                    "verified memory path passed"
                ),
            }
        ],
        "reward": 1.0,
        "provider_identity": "nifdu_browser",
        "model_identity": "chatgpt-browser",
        "session_mode": "nifdu_llm",
        "capability_class": "cognitive-memory-test",
        "result": (
            "The verified lesson contains "
            + token
            + ". "
            + noise
        ),
        "created_at": 1800000000.0,
    }


def test_sparse_projection_is_lossy_and_trusted():
    from sophyane.cognitive_memory import (
        sparse_projection,
    )

    token = (
        "COGNITIVE_TOKEN_"
        "SPARSE_CEDAR_4417"
    )

    event = _episode(
        token
    )

    projected = sparse_projection(
        event
    )

    assert projected["ok"] is True

    memory = projected["memory"]

    assert memory["trusted"] is True
    assert memory["verified_origin"] is True
    assert memory["lossy_projection"] is True
    assert (
        memory["instruction_authority"]
        is False
    )

    text = json.dumps(
        memory,
        ensure_ascii=False,
    )

    assert token in text

    #
    # The entire raw result must not become memory.
    #
    assert event["result"] not in text

    assert len(
        memory["fragments"]
    ) <= 5

    assert sum(
        len(
            item["content"]
        )
        for item in memory["fragments"]
    ) <= 1200


def test_unverified_episode_cannot_become_sparse_memory():
    from sophyane.cognitive_memory import (
        sparse_projection,
    )

    event = _episode(
        "COGNITIVE_UNVERIFIED_9911"
    )

    event[
        "verification_state"
    ] = "unverified"

    event[
        "accepted"
    ] = False

    result = sparse_projection(
        event
    )

    assert result["ok"] is False


def test_thought_is_temporary_activation(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(
            tmp_path
        ),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
        form_thought,
        recall_sparse_memories,
    )

    token = (
        "COGNITIVE_THOUGHT_TOKEN_"
        "MAPLE_8241"
    )

    result = consolidate_verified_episode(
        _episode(
            token
        )
    )

    assert result["ok"] is True

    rows = recall_sparse_memories(
        "important verified marker maple",
        limit=8,
    )

    assert rows

    thought = form_thought(
        "important verified marker maple",
        limit=5,
    )

    assert thought["kind"] == "thought"
    assert thought["persisted"] is False
    assert thought["trusted"] is False
    assert (
        thought[
            "instruction_authority"
        ]
        is False
    )

    text = json.dumps(
        thought,
        ensure_ascii=False,
    )

    assert token in text


def test_thought_activation_reinforces_memory(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(
            tmp_path
        ),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
        form_thought,
        recall_sparse_memories,
    )

    token = (
        "COGNITIVE_REINFORCE_TOKEN_"
        "ASH_5102"
    )

    consolidate_verified_episode(
        _episode(
            token
        )
    )

    before = recall_sparse_memories(
        "reinforce ash verified marker",
    )

    assert before

    strength_before = before[0][
        "strength"
    ]

    count_before = before[0][
        "activation_count"
    ]

    form_thought(
        "reinforce ash verified marker",
    )

    after = recall_sparse_memories(
        "reinforce ash verified marker",
    )

    assert after

    assert (
        after[0][
            "activation_count"
        ]
        > count_before
    )

    assert (
        after[0][
            "strength"
        ]
        >= strength_before
    )


def test_dream_is_persisted_but_never_trusted(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(
            tmp_path
        ),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
        dream_cycle,
        recall_dreams,
        recall_sparse_memories,
    )

    consolidate_verified_episode(
        _episode(
            "DREAM_SHARED_CEDAR_ALPHA_1001"
        )
    )

    second = _episode(
        "DREAM_SHARED_CEDAR_BETA_1002"
    )

    second[
        "trace_id"
    ] = "dream-second-trace"

    second[
        "event_key"
    ] = "dream-second-event"

    second[
        "original_objective"
    ] = (
        "A second verified cedar experience "
        "shares a memory retrieval pattern."
    )

    consolidate_verified_episode(
        second
    )

    result = dream_cycle(
        seed="cedar memory retrieval",
        limit=6,
    )

    assert result["ok"] is True

    dream = result["dream"]

    assert dream["kind"] == "dream"
    assert dream["verified"] is False
    assert dream["trusted"] is False
    assert dream["accepted"] is False
    assert (
        dream[
            "instruction_authority"
        ]
        is False
    )

    dreams = recall_dreams()

    assert dreams

    assert all(
        item["trusted"] is False
        and item["verified"] is False
        and item["accepted"] is False
        and item[
            "instruction_authority"
        ] is False
        for item in dreams
    )

    #
    # Dreams live in a separate namespace and never
    # silently become trusted sparse memories.
    #
    trusted = recall_sparse_memories(
        "possible association",
        limit=16,
    )

    assert all(
        item.get(
            "kind"
        )
        == "sparse_memory"
        for item in trusted
    )


def test_episode_writer_derives_sparse_memory(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(
            tmp_path
        ),
    )

    from sophyane.episodic_memory import (
        persist_execution_episode,
    )

    from sophyane.cognitive_memory import (
        recall_sparse_memories,
    )

    token = (
        "AUTO_CONSOLIDATE_TOKEN_"
        "BIRCH_6632"
    )

    result = persist_execution_episode(
        _episode(
            token
        )
    )

    assert result["ok"] is True
    assert result["trusted"] is True

    cognitive = result.get(
        "cognitive_memory"
    )

    assert isinstance(
        cognitive,
        dict,
    )

    assert cognitive["ok"] is True

    rows = recall_sparse_memories(
        "birch important verified marker",
        limit=8,
    )

    assert rows

    assert token in json.dumps(
        rows,
        ensure_ascii=False,
    )


def test_dream_filters_bookkeeping_associations(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
        dream_cycle,
    )

    def episode(
        trace_id,
        subject,
    ):
        return {
            "trace_id": trace_id,
            "event_key": trace_id,
            "original_objective": (
                "Explore cedar adaptive cognition "
                + subject
            ),
            "status": "succeeded",
            "accepted": True,
            "verification_state": "verified",
            "verification_evidence": [
                {
                    "validator": "deterministic",
                    "passed": True,
                    "source_dream_id": (
                        "dream:test"
                    ),
                }
            ],
            "reward": 1.0,
            "provider_identity": "nifdu_browser",
            "model_identity": "chatgpt-browser",
            "session_mode": "nifdu_llm",
            "capability_class": "test",
            "result": (
                "Cedar adaptive cognition "
                + subject
                + " produced useful evidence."
            ),
        }

    assert (
        consolidate_verified_episode(
            episode(
                "phase9-test-one",
                "memory",
            )
        )["ok"]
        is True
    )

    assert (
        consolidate_verified_episode(
            episode(
                "phase9-test-two",
                "learning",
            )
        )["ok"]
        is True
    )

    result = dream_cycle(
        seed="cedar adaptive cognition",
        limit=6,
    )

    assert result["ok"] is True

    recurring = set(
        result["dream"][
            "recurring_terms"
        ]
    )

    # Semantic overlap should survive.
    assert "cedar" in recurring
    assert "adaptive" in recurring
    assert "cognition" in recurring

    # Serialization / verification machinery must not become thought.
    forbidden = {
        "verified",
        "validator",
        "true",
        "passed",
        "source_dream_id",
        "verification_state",
        "provider_identity",
        "session_mode",
    }

    assert not (
        recurring
        & forbidden
    )

    assert not any(
        term.startswith(
            "phase9"
        )
        for term in recurring
    )


def test_sentence_regex_splits_real_whitespace():
    from sophyane.cognitive_memory import (
        _SENTENCE_RE,
    )

    parts = [
        value
        for value in _SENTENCE_RE.split(
            "First sentence. Second sentence.\nThird sentence."
        )
        if value
    ]

    assert parts == [
        "First sentence.",
        "Second sentence.",
        "Third sentence.",
    ]
