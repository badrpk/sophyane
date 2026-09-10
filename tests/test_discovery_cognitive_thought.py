import json


def test_provider_gets_sparse_thought_not_raw_episode(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(
            tmp_path
        ),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
    )

    token = (
        "NIFDU_THOUGHT_TOKEN_"
        "WILLOW_7428"
    )

    raw_noise = (
        "RAW_EPISODE_NOISE_BEGIN "
        + " ".join(
            f"raw_noise_{i}"
            for i in range(400)
        )
        + " RAW_EPISODE_NOISE_END"
    )

    event = {
        "trace_id": "thought-provider-trace",
        "event_key": "thought-provider-event",
        "original_objective": (
            "Remember verified willow marker "
            + token
            + " for memory reasoning."
        ),
        "status": "succeeded",
        "accepted": True,
        "verification_state": "verified",
        "verification_evidence": [
            {
                "validator": "test",
                "passed": True,
            }
        ],
        "reward": 1.0,
        "provider_identity": "nifdu_browser",
        "model_identity": "chatgpt-browser",
        "session_mode": "nifdu_llm",
        "capability_class": "thought-test",
        "result": (
            "Verified willow lesson. "
            + raw_noise
        ),
    }

    assert (
        consolidate_verified_episode(
            event
        )["ok"]
        is True
    )

    captured = []

    class FakeProvider:
        provider_id = "nifdu_browser"

        def generate(
            self,
            prompt,
            system_prompt="",
        ):
            captured.append(
                {
                    "prompt": str(
                        prompt
                    ),
                    "system_prompt": str(
                        system_prompt
                    ),
                }
            )

            return json.dumps(
                {
                    "hypotheses": [
                        {
                            "statement": (
                                "Sparse thought context "
                                "is available."
                            ),
                            "rationale": token,
                            "predictions": [
                                "The marker appears "
                                "in activated memory."
                            ],
                            "assumptions": [],
                        }
                    ]
                }
            )

    from sophyane.discovery_provider_reasoner import (
        SessionProviderReasoner,
    )

    reasoner = SessionProviderReasoner(
        provider_factory=(
            lambda: FakeProvider()
        )
    )

    raw_episodic_record = {
        "source": (
            "xerus_execution_episodes"
        ),
        "kind": (
            "verified_episodic_memory"
        ),
        "score": 1.0,
        "content": raw_noise,
        "metadata": {
            "instruction_authority": False,
        },
    }

    response = reasoner(
        "generate_hypotheses",
        {
            "objective": (
                "Reason about verified willow "
                "memory marker."
            ),
            "knowledge": [
                raw_episodic_record,
            ],
            "requirements": {
                "maximum": 1,
            },
            "return_schema": {
                "hypotheses": [
                    {
                        "statement": "string",
                        "rationale": "string",
                        "predictions": [
                            "string"
                        ],
                        "assumptions": [
                            "string"
                        ],
                    }
                ]
            },
        },
    )

    assert captured

    combined = (
        captured[0][
            "system_prompt"
        ]
        + "\n"
        + captured[0][
            "prompt"
        ]
    )

    #
    # Important sparse detail survives.
    #
    assert token in combined

    #
    # Raw Xerus episode dump is not sent to the provider.
    #
    assert (
        "RAW_EPISODE_NOISE_END"
        not in combined
    )

    assert (
        "sophyane_cognitive_thought"
        in combined
    )

    parsed = json.loads(
        response
    )

    assert parsed["hypotheses"]
