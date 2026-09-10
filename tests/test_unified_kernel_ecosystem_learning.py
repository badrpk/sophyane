def test_execute_request_attaches_badrpk_capability_plan(
    monkeypatch,
    tmp_path,
):
    import sophyane.unified_execution_kernel as kernel
    import sophyane.ecosystem_capabilities as ecosystem
    import sophyane.execution_experience as experience

    captured = {}

    monkeypatch.setattr(
        ecosystem,
        "capability_plan_dict",
        lambda *args, **kwargs: {
            "objective": args[0],
            "repositories": [
                {
                    "repository": "neuron",
                    "available": True,
                    "score": 0.8,
                }
            ],
            "discovered": [
                "neuron",
            ],
            "unavailable": [],
        },
    )

    class FakeRegistry:
        def execute(
            self,
            request,
        ):
            captured[
                "metadata"
            ] = request.metadata

            return None

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: FakeRegistry(),
    )

    monkeypatch.setattr(
        experience,
        "record_execution_experience",
        lambda **kwargs: captured.setdefault(
            "experience",
            kwargs,
        ),
    )

    result = (
        kernel.execute_request(
            "Use repository intelligence",
            workspace=tmp_path,
        )
    )

    assert result is None

    plan = captured[
        "metadata"
    ][
        "badrpk_capability_plan"
    ]

    assert (
        plan[
            "repositories"
        ][0][
            "repository"
        ]
        == "neuron"
    )

    assert (
        captured[
            "experience"
        ][
            "request_text"
        ]
        == "Use repository intelligence"
    )
