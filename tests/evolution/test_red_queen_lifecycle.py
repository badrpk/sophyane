from sophyane.evolution.red_queen import (
    STATUS_ACTIVE,
    EvaluatorSpec,
    RedQueenState,
    build_adversarial_challenger,
    coevolution_round,
    compare_evaluators,
    promote_at_epoch_boundary,
    run_bounded_red_queen,
    selectively_invalidate_utility,
)


def active():
    return EvaluatorSpec(
        evaluator_id="judge-v1",
        version=1,
        objective="detect correctness failures",
        tests=("base::correctness",),
        generation=0,
        status=STATUS_ACTIVE,
    )


def state():
    return RedQueenState(
        epoch=1,
        trusted_anchor_id="anchor-static-v1",
        active=active(),
    )


def test_adversarial_challenger_targets_observed_failures():
    challenger = build_adversarial_challenger(
        incumbent=active(),
        observed_failures=[
            "missed iterator consumption bug",
            "missed conversion ordering bug",
        ],
        evaluator_id="judge-v2",
    )

    assert challenger.adversarial is True
    assert challenger.parent_id == "judge-v1"
    assert challenger.version == 2
    assert challenger.generation == 1

    assert (
        "iterator consumption"
        in challenger.objective
    )

    assert len(challenger.tests) == 2


def test_trusted_anchor_blocks_bad_challenger():
    incumbent = active()

    challenger = build_adversarial_challenger(
        incumbent=incumbent,
        observed_failures=["hidden regression"],
        evaluator_id="judge-v2",
    )

    match = compare_evaluators(
        incumbent=incumbent,
        challenger=challenger,
        incumbent_detection_score=0.60,
        challenger_detection_score=0.95,
        trusted_anchor_score=0.50,
    )

    assert match.challenger_wins is False
    assert "anchor" in match.reason


def test_challenger_must_actually_beat_incumbent():
    incumbent = active()

    challenger = build_adversarial_challenger(
        incumbent=incumbent,
        observed_failures=["failure"],
        evaluator_id="judge-v2",
    )

    match = compare_evaluators(
        incumbent=incumbent,
        challenger=challenger,
        incumbent_detection_score=0.90,
        challenger_detection_score=0.89,
        trusted_anchor_score=1.0,
    )

    assert match.challenger_wins is False


def test_evaluator_promotes_only_at_epoch_transition():
    current = state()

    challenger = build_adversarial_challenger(
        incumbent=current.active,
        observed_failures=["failure"],
        evaluator_id="judge-v2",
    )

    current.register_challenger(
        challenger
    )

    match = compare_evaluators(
        incumbent=current.active,
        challenger=challenger,
        incumbent_detection_score=0.60,
        challenger_detection_score=0.90,
        trusted_anchor_score=1.0,
    )

    decision = promote_at_epoch_boundary(
        current,
        challenger_id="judge-v2",
        match=match,
    )

    assert decision.accepted is True
    assert current.epoch == 2
    assert current.active.evaluator_id == "judge-v2"
    assert current.active.status == STATUS_ACTIVE
    assert "judge-v1" in current.retired


def test_utility_records_include_evaluator_version_and_identity():
    current = state()

    outcome = current.record_outcome(
        candidate_id="candidate-a",
        evaluator=current.active,
        score=0.75,
        passed=True,
        evidence=["test evidence"],
    )

    assert outcome.evaluator_id == "judge-v1"
    assert outcome.evaluator_version == 1
    assert len(outcome.evaluator_identity) == 64
    assert outcome.epoch == 1


def test_selective_invalidation_does_not_erase_other_evaluators():
    current = state()

    old = current.active

    second = EvaluatorSpec(
        evaluator_id="judge-v2",
        version=2,
        objective="new",
        tests=("new",),
        status=STATUS_ACTIVE,
    )

    current.record_outcome(
        candidate_id="candidate-a",
        evaluator=old,
        score=0.20,
        passed=False,
    )

    current.record_outcome(
        candidate_id="candidate-a",
        evaluator=second,
        score=0.90,
        passed=True,
    )

    count = selectively_invalidate_utility(
        current,
        evaluator_identity=old.identity(),
    )

    assert count == 1

    records = current.ledger.valid_records()

    assert len(records) == 1
    assert records[0].evaluator_id == "judge-v2"
    assert (
        current.ledger.utility_for(
            "candidate-a"
        )
        == 0.90
    )


def test_coevolution_round_promotes_and_invalidates_old_utility():
    current = state()

    old_identity = (
        current.active.identity()
    )

    decision = coevolution_round(
        current,
        candidate_id="candidate-a",
        observed_failures=[
            "incumbent missed semantic edge case"
        ],
        challenger_id="judge-v2",
        incumbent_detection_score=0.55,
        challenger_detection_score=0.90,
        trusted_anchor_score=0.98,
    )

    assert decision.accepted is True
    assert current.active.evaluator_id == "judge-v2"
    assert current.epoch == 2

    assert (
        old_identity
        in current.ledger.invalidated_identities
    )


def test_failed_challenger_does_not_replace_incumbent():
    current = state()

    decision = coevolution_round(
        current,
        candidate_id="candidate-a",
        observed_failures=["suspected issue"],
        challenger_id="judge-v2",
        incumbent_detection_score=0.90,
        challenger_detection_score=0.50,
        trusted_anchor_score=1.0,
    )

    assert decision.accepted is False
    assert current.active.evaluator_id == "judge-v1"
    assert current.epoch == 1
    assert "judge-v2" in current.rejected


def test_trusted_anchor_cannot_be_registered_as_challenger():
    current = state()

    fake_anchor = EvaluatorSpec(
        evaluator_id="anchor-static-v1",
        version=99,
        objective="evil replacement",
        tests=("x",),
    )

    try:
        current.register_challenger(
            fake_anchor
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "trusted anchor was replaceable"
        )


def test_open_loop_is_bounded_by_max_epochs():
    current = state()

    decisions = run_bounded_red_queen(
        current,
        candidate_id="candidate-a",
        failure_batches=[
            ["f1"],
            ["f2"],
            ["f3"],
            ["f4"],
        ],
        scores=[
            (0.50, 0.80, 1.0),
            (0.50, 0.80, 1.0),
            (0.50, 0.80, 1.0),
            (0.50, 0.80, 1.0),
        ],
        max_epochs=2,
    )

    assert len(decisions) == 2
    assert current.epoch == 3


def test_identity_changes_when_evaluator_version_changes():
    first = EvaluatorSpec(
        evaluator_id="judge",
        version=1,
        objective="x",
        tests=("a",),
    )

    second = EvaluatorSpec(
        evaluator_id="judge",
        version=2,
        objective="x",
        tests=("a",),
    )

    assert (
        first.identity()
        != second.identity()
    )


def test_identical_evaluator_semantics_have_stable_identity():
    first = EvaluatorSpec(
        evaluator_id="judge",
        version=1,
        objective="x",
        tests=("a",),
        created_at=1,
    )

    second = EvaluatorSpec(
        evaluator_id="judge",
        version=1,
        objective="x",
        tests=("a",),
        created_at=999,
    )

    assert (
        first.identity()
        == second.identity()
    )
