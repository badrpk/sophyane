from tools.experimental_rsi_campaign import assess_samples, validate_candidate_files


def test_assess_samples_accepts_repeatable_gain_above_threshold():
    result = assess_samples(
        [100.0, 101.0, 99.0, 100.0, 102.0, 98.0, 100.0],
        [120.0, 122.0, 119.0, 121.0, 123.0, 118.0, 120.0],
        minimum_improvement=0.05,
    )

    assert result["accepted"] is True
    assert result["median_improvement"] >= 0.05
    assert result["positive_pairs"] == 7
    assert result["bootstrap_lower_bound"] > 0


def test_assess_samples_rejects_noisy_small_gain():
    result = assess_samples(
        [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        [106.0, 94.0, 105.0, 95.0, 106.0, 94.0, 100.0],
        minimum_improvement=0.05,
    )

    assert result["accepted"] is False


def test_agent_candidate_must_change_only_the_allowlisted_target():
    baseline = {"src/sophyane/rsi/models.py": b"before"}
    accepted = validate_candidate_files(
        baseline,
        {"src/sophyane/rsi/models.py": b"after"},
        target="src/sophyane/rsi/models.py",
    )
    assert accepted["src/sophyane/rsi/models.py"] == b"after"

    try:
        validate_candidate_files(
            baseline,
            {
                "src/sophyane/rsi/models.py": b"after",
                "src/sophyane/rsi/authority.py": b"unauthorized",
            },
            target="src/sophyane/rsi/models.py",
        )
    except ValueError as error:
        assert "only the target file" in str(error)
    else:
        raise AssertionError("candidate changed a file outside its target allowlist")
