from pathlib import Path

from sophyane.agentic_memory import (
    MemoryAction,
    MemoryProvenance,
    apply_verified_memory_action,
    augment_instruction_with_memory,
    consolidate_memories,
    learn_verified_mode3_experience,
    load_memory_store,
    memory_stats,
    parse_memory_action,
    record_memory_failure,
    retrieve_memories,
    store_verified_memory,
)


def verified_provenance():
    return MemoryProvenance(
        source="test",
        task_family="python",
        candidate_identity="candidate-1",
        verification_ok=True,
        held_out_attempted=True,
        held_out_not_regressed=True,
    )


def test_unverified_memory_cannot_enter_ltm(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    record, created = (
        store_verified_memory(
            text="never trust unverified output",
            provenance=MemoryProvenance(
                verification_ok=False,
            ),
            path=path,
        )
    )

    assert record is None
    assert created is False


def test_held_out_regression_blocks_memory(
    tmp_path: Path,
):
    record, created = (
        store_verified_memory(
            text="bad generalization",
            provenance=MemoryProvenance(
                verification_ok=True,
                held_out_attempted=True,
                held_out_not_regressed=False,
            ),
            path=(
                tmp_path
                / "memory.json"
            ),
        )
    )

    assert record is None
    assert created is False


def test_verified_memory_is_persistent(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    record, created = (
        store_verified_memory(
            text=(
                "Use deterministic verification "
                "before reporting success."
            ),
            tags=(
                "verification",
                "mode3",
            ),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )
    )

    assert record is not None
    assert created is True

    store = load_memory_store(
        path
    )

    assert (
        record.memory_id
        in store["records"]
    )


def test_same_verified_memory_deduplicates(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    kwargs = {
        "text":
            "retry transient failures only",
        "tags":
            (
                "retry",
            ),
        "provenance":
            verified_provenance(),
        "path":
            path,
    }

    first, first_created = (
        store_verified_memory(
            **kwargs
        )
    )

    second, second_created = (
        store_verified_memory(
            **kwargs
        )
    )

    assert first is not None
    assert second is not None
    assert (
        first.memory_id
        == second.memory_id
    )

    assert first_created is True
    assert second_created is False


def test_retrieval_prefers_relevant_memory(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    store_verified_memory(
        text=(
            "Redis rate limiting should "
            "return HTTP 429 at the boundary."
        ),
        tags=(
            "redis",
            "rate-limit",
        ),
        provenance=(
            verified_provenance()
        ),
        path=path,
    )

    store_verified_memory(
        text=(
            "CSS cards should use "
            "consistent spacing."
        ),
        tags=(
            "css",
        ),
        provenance=(
            verified_provenance()
        ),
        path=path,
    )

    memories = retrieve_memories(
        objective=(
            "repair redis rate limit 429 behavior"
        ),
        difficulty=4,
        quality_target=0.9,
        path=path,
    )

    assert memories

    assert (
        "Redis"
        in memories[0].text
    )


def test_txq_context_budget_bounds_memory(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    for index in range(20):
        store_verified_memory(
            text=(
                "parser verification rule "
                + str(index)
                + " "
                + (
                    "x"
                    * 300
                )
            ),
            tags=(
                "parser",
            ),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )

    rendered, memories = (
        augment_instruction_with_memory(
            "repair parser",
            objective="repair parser",
            difficulty=4,
            quality_target=0.9,
            context_budget_chars=2000,
            path=path,
        )
    )

    assert (
        "VERIFIED_LONG_TERM_MEMORY"
        in rendered
    )

    assert len(
        memories
    ) <= 8


def test_memory_action_parser():
    action = parse_memory_action(
        (
            'MEMORY_ACTION_JSON: '
            '{"action":"STORE",'
            '"text":"verify timeout behavior",'
            '"tags":["timeout","verification"],'
            '"confidence":0.9}'
        )
    )

    assert action is not None

    assert action.action == "STORE"

    assert (
        action.confidence
        == 0.9
    )


def test_invalid_memory_action_rejected():
    assert (
        parse_memory_action(
            (
                'MEMORY_ACTION_JSON: '
                '{"action":"GIT_PUSH",'
                '"text":"bad"}'
            )
        )
        is None
    )


def test_llm_memory_action_requires_real_verification(
    tmp_path: Path,
):
    action = MemoryAction(
        action="STORE",
        text=(
            "unverified statement"
        ),
    )

    accepted = (
        apply_verified_memory_action(
            action,
            provenance=(
                MemoryProvenance(
                    verification_ok=False,
                )
            ),
            path=(
                tmp_path
                / "memory.json"
            ),
        )
    )

    assert accepted is False


def test_verified_memory_action_can_store(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    accepted = (
        apply_verified_memory_action(
            MemoryAction(
                action="STORE",
                text=(
                    "preserve cancellation "
                    "quiescence before retry"
                ),
                tags=(
                    "retry",
                    "cancellation",
                ),
                confidence=0.9,
            ),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )
    )

    assert accepted is True

    assert (
        memory_stats(
            path
        )["active"]
        == 1
    )


def test_verified_mode3_experience_learning(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    record, created = (
        learn_verified_mode3_experience(
            objective="repair parser",
            candidate_identity="candidate-x",
            candidate_diff=(
                "+ return parsed_value"
            ),
            task_family="debugging",
            verification_ok=True,
            held_out_attempted=True,
            held_out_not_regressed=True,
            review_status="SUCCESS",
            path=path,
        )
    )

    assert record is not None
    assert created is True


def test_failed_mode3_candidate_not_learned(
    tmp_path: Path,
):
    record, created = (
        learn_verified_mode3_experience(
            objective="repair parser",
            candidate_identity="candidate-x",
            candidate_diff=(
                "+ broken"
            ),
            task_family="debugging",
            verification_ok=False,
            held_out_attempted=False,
            held_out_not_regressed=True,
            review_status="CONTINUE",
            path=(
                tmp_path
                / "memory.json"
            ),
        )
    )

    assert record is None
    assert created is False


def test_repeated_negative_evidence_demotes_memory(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    record, _ = (
        store_verified_memory(
            text=(
                "old implementation strategy"
            ),
            tags=(
                "strategy",
            ),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )
    )

    assert record is not None

    for _ in range(3):
        assert (
            record_memory_failure(
                record.memory_id,
                path=path,
            )
            is True
        )

    raw = (
        load_memory_store(
            path
        )[
            "records"
        ][
            record.memory_id
        ]
    )

    assert (
        raw["active"]
        is False
    )


def test_verified_consolidation_replaces_raw_memories(
    tmp_path: Path,
):
    path = tmp_path / "memory.json"

    first, _ = (
        store_verified_memory(
            text="redis incident one",
            tags=("redis",),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )
    )

    second, _ = (
        store_verified_memory(
            text="redis incident two",
            tags=("redis",),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )
    )

    assert first is not None
    assert second is not None

    consolidated = (
        consolidate_memories(
            memory_ids=(
                first.memory_id,
                second.memory_id,
            ),
            consolidated_text=(
                "For Redis rate limits, "
                "verify the exact rejection boundary."
            ),
            tags=(
                "redis",
                "principle",
            ),
            provenance=(
                verified_provenance()
            ),
            path=path,
        )
    )

    assert consolidated is not None

    store = load_memory_store(
        path
    )

    assert (
        store[
            "records"
        ][
            first.memory_id
        ][
            "active"
        ]
        is False
    )

    assert (
        store[
            "records"
        ][
            second.memory_id
        ][
            "active"
        ]
        is False
    )


def test_memory_stats_are_bounded_shape(
    tmp_path: Path,
):
    stats = memory_stats(
        tmp_path
        / "memory.json"
    )

    assert set(
        (
            "total",
            "active",
            "inactive",
            "mean_confidence",
            "mean_utility",
        )
    ).issubset(
        stats
    )
