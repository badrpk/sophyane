from __future__ import annotations

from sophyane.global_txq import (
    choose_global_txq_policy,
    mode4_txq_context,
    readonly_speculation_contract,
)


def test_global_txq_has_policy_for_all_five_modes():
    for mode in range(
        1,
        6,
    ):
        policy = choose_global_txq_policy(
            mode,
            "repair one bounded regression test",
        )

        assert policy.mode == mode
        assert policy.wall_time_budget_sec > 0
        assert policy.context_budget_chars > 0
        assert 0.0 < policy.quality_target <= 1.0


def test_global_txq_never_allows_speculative_mutation():
    for mode in range(
        1,
        6,
    ):
        policy = choose_global_txq_policy(
            mode,
            "recursive repository repair",
        )

        assert (
            policy.allow_speculative_mutation
            is False
        )


def test_mode2_global_txq_does_not_add_llm_authority():
    policy = choose_global_txq_policy(
        2,
        "SLI graph task",
    )

    assert policy.allow_llm is False


def test_mode3_global_policy_delegates_existing_txq():
    policy = choose_global_txq_policy(
        3,
        (
            "repair a difficult recursive "
            "repository regression"
        ),
    )

    assert (
        "mode3_existing_txq"
        in policy.rationale
    )

    assert (
        policy.allow_speculative_readonly
        is True
    )


def test_mode4_txq_is_latency_aware():
    fast = choose_global_txq_policy(
        4,
        "review repository candidate",
        observed_latency_sec=0,
    )

    slow = choose_global_txq_policy(
        4,
        "review repository candidate",
        observed_latency_sec=90,
    )

    assert (
        slow.wall_time_budget_sec
        >= fast.wall_time_budget_sec
    )

    assert (
        slow.context_budget_chars
        == fast.context_budget_chars
    )


def test_mode4_context_contains_global_contract():
    policy, rendered = mode4_txq_context(
        "review one bounded candidate"
    )

    assert policy.mode == 4

    assert (
        "SOPHYANE_GLOBAL_TXQ"
        in rendered
    )

    assert (
        "allow_speculative_mutation=0"
        in rendered
    )


def test_readonly_speculation_contract_forbids_change_selection():
    rendered = readonly_speculation_contract(
        "improve one RSI regression test"
    ).casefold()

    assert (
        "mode 4 has not selected"
        in rendered
    )

    assert (
        "do not choose an implementation"
        in rendered
    )

    assert (
        "do not write"
        in rendered
    )

    assert (
        "deterministic verification commands"
        in rendered
    )


def test_adaptive_speculation_timeout_uses_short_cold_start():
    from sophyane.global_txq import (
        adaptive_speculative_timeout_sec,
    )

    assert (
        adaptive_speculative_timeout_sec()
        == 3
    )


def test_adaptive_speculation_timeout_tracks_mode4_but_is_clamped():
    from sophyane.global_txq import (
        adaptive_speculative_timeout_sec,
    )

    assert (
        adaptive_speculative_timeout_sec(
            3.28
        )
        == 3
    )

    assert (
        adaptive_speculative_timeout_sec(
            8.0
        )
        == 6
    )

    assert (
        adaptive_speculative_timeout_sec(
            100.0
        )
        == 8
    )


def test_mode4_v4_policy_uses_one_short_speculative_loop():
    from sophyane.global_txq import (
        choose_global_txq_policy,
    )

    policy = choose_global_txq_policy(
        4,
        (
            "review one bounded repository "
            "regression candidate"
        ),
        observed_latency_sec=3.28,
    )

    assert (
        policy.max_speculative_loops
        == 1
    )

    assert (
        3
        <= policy.speculative_timeout_sec
        <= 8
    )

    assert (
        policy.speculative_max_tokens
        <= 96
    )

    assert (
        policy.allow_speculative_mutation
        is False
    )


def test_global_txq_render_exposes_v4_speculation_budget():
    from sophyane.global_txq import (
        choose_global_txq_policy,
        render_global_txq_context,
    )

    policy = choose_global_txq_policy(
        4,
        "bounded review",
    )

    rendered = render_global_txq_context(
        policy
    )

    assert (
        "speculative_timeout_sec="
        in rendered
    )

    assert (
        "speculative_max_tokens="
        in rendered
    )


def test_mode4_v5_speculation_uses_compact_evidence_budget():
    from sophyane.global_txq import (
        choose_global_txq_policy,
    )

    policy = choose_global_txq_policy(
        4,
        "one bounded repository regression",
    )

    assert (
        policy.max_speculative_loops
        == 1
    )

    assert (
        policy.speculative_timeout_sec
        == 3
    )

    assert (
        policy.speculative_max_tokens
        == 96
    )


def test_verified_history_is_bounded_and_softly_influences_policy(monkeypatch):
    import sophyane.global_txq as txq

    calls = []
    records = [{
        "accepted": True,
        "verification_state": "verified",
        "status": "succeeded",
        "objective_hash": "h" * 64,
        "repository_identity": "repo-a",
        "capability_class": "external_api",
        "provider_identity": "api:test",
        "reward": 1.0,
    }]

    def read(**kwargs):
        calls.append(kwargs)
        return records

    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", read)
    policy = txq.choose_global_txq_policy(
        1,
        "build a repository artifact",
        objective_hash="h" * 64,
        repository_identity="repo-a",
        capability_class="external_api",
        provider_identity="api:test",
        history_limit=3,
    )
    assert calls[0]["limit"] == 3
    assert policy.verified_history.checked is True
    assert policy.verified_history.matching_repository_successes == 1
    assert policy.verified_history.matching_capability_successes == 1
    assert policy.verified_history.matching_provider_successes == 1
    assert policy.verified_history.influenced is True
    assert "verified_history_influenced" in policy.rationale
    assert "verified_history_hits=1" in txq.render_global_txq_context(policy)


def test_history_cannot_change_hard_mode_authority(monkeypatch):
    import sophyane.global_txq as txq

    monkeypatch.setattr(
        "sophyane.sli_learner.read_verified_history",
        lambda **kwargs: [{
            "accepted": True,
            "verification_state": "verified",
            "status": "succeeded",
            "capability_class": "external_api",
            "reward": 1.0,
        }],
    )
    policy = txq.choose_global_txq_policy(
        2,
        "repository memory lookup",
        capability_class="external_api",
    )
    assert policy.allow_llm is False
    assert policy.allow_speculative_mutation is False


def test_history_unavailable_fails_open(monkeypatch):
    import sophyane.global_txq as txq

    monkeypatch.setattr(
        "sophyane.sli_learner.read_verified_history",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    policy = txq.choose_global_txq_policy(
        1,
        "ordinary task",
    )
    assert policy.verified_history.checked is False
    assert "verified_history_checked" not in policy.rationale


def test_verified_history_reader_excludes_untrusted_rows_and_is_bounded(tmp_path, monkeypatch):
    import json
    import sqlite3
    import sophyane.sli as storage
    import sophyane.sli_learner as learner

    database = tmp_path / "sli.db"
    monkeypatch.setattr(storage, "DB_PATH", database)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE learned_execution_traces (trace_id TEXT, created_at REAL, provenance_json TEXT)")
        trusted = {"accepted": True, "verification_state": "verified", "status": "succeeded", "objective_hash": "a"}
        rejected = {"accepted": False, "verification_state": "verified", "status": "succeeded", "objective_hash": "b"}
        db.executemany(
            "INSERT INTO learned_execution_traces VALUES (?, ?, ?)",
            [("trusted", 2, json.dumps(trusted, separators=(",", ":"))), ("rejected", 1, json.dumps(rejected, separators=(",", ":")))],
        )
        db.commit()
    rows = learner.read_verified_history(objective_hash="a", limit=1)
    assert len(rows) == 1
    assert rows[0]["objective_hash"] == "a"


