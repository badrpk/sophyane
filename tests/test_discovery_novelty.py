def test_identical_candidate_is_not_novel():
    from sophyane.discovery_novelty import (
        novelty_score,
    )

    score, reason = novelty_score(
        "adaptive disk memory retrieval",
        [
            "adaptive disk memory retrieval",
        ],
    )

    assert score == 0.0
    assert "max_known_similarity" in reason


def test_different_candidate_scores_more_novel():
    from sophyane.discovery_novelty import (
        novelty_score,
    )

    score, _ = novelty_score(
        (
            "spiking temporal adaptation "
            "for autonomous visual repair"
        ),
        [
            (
                "relational database "
                "transaction scheduler"
            )
        ],
    )

    assert score > 0.5
