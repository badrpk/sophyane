

def test_topic_site_graph_records_validated_execution_learning(
    tmp_path,
    monkeypatch,
):
    from unittest.mock import patch

    from sophyane.sli_graph import (
        run_sli_graph,
    )

    report = (
        "Sophyane rich SLI website orchestrator\n"
        "Validation: passed\n"
        "Browser opened: False\n"
        "Success: True"
    )

    def compose(
        request,
        workspace,
        *,
        progress=None,
    ):
        del request, progress

        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        (
            workspace
            / "index.html"
        ).write_text(
            (
                "<!doctype html>"
                "<html>"
                "<body>"
                "<button>Open</button>"
                "<script>"
                "document.querySelector('button')"
                ".addEventListener('click',()=>{});"
                "</script>"
                "</body>"
                "</html>"
            ),
            encoding="utf-8",
        )

        return report

    promotion = {
        "ok": True,
        "chunks_added": 2,
        "reason": "promoted",
    }

    learned = {
        "quality_reward": 0.85,
        "quality_signals": [
            "successful_status:+0.35",
            "artifact_created:+0.20",
            "validation_passed:+0.20",
            "no_detected_runtime_error:+0.10",
        ],
        "failure_category": "",
    }

    with (
        patch(
            "sophyane.code_memory."
            "sli_rich_site_compose."
            "compose_rich_topic_site",
            side_effect=compose,
        ),
        patch(
            "sophyane.code_memory."
            "promote_success."
            "promote_workspace",
            return_value=promotion,
        ),
        patch(
            "sophyane.sli_schema."
            "ensure_current_schema",
        ),
        patch(
            "sophyane.sli_learner."
            "learn_execution",
            return_value=learned,
        ) as learner,
    ):
        state = run_sli_graph(
            "make website on demis hassabis",
            workspace=tmp_path,
            max_retries=1,
        )

    assert state.success is True
    assert state.promoted is True

    learner.assert_called_once()

    kwargs = learner.call_args.kwargs

    assert kwargs["status"] == "succeeded"
    assert kwargs["request"] == (
        "make website on demis hassabis"
    )

    assert kwargs[
        "workspace_before"
    ]["sample"] == []

    assert any(
        item["path"] == "index.html"
        for item in kwargs[
            "workspace_after"
        ]["sample"]
    )

    assert (
        state.meta["learning"][
            "quality_reward"
        ]
        == 0.85
    )


def test_topic_site_graph_learns_failure_when_promotion_rejected(
    tmp_path,
):
    from unittest.mock import patch

    from sophyane.sli_graph import (
        run_sli_graph,
    )

    report = (
        "Sophyane rich SLI website orchestrator\n"
        "Validation: passed\n"
        "Success: True"
    )

    def compose(
        request,
        workspace,
        *,
        progress=None,
    ):
        del request, progress

        (
            workspace
            / "index.html"
        ).write_text(
            "<html><body>site</body></html>",
            encoding="utf-8",
        )

        return report

    promotion = {
        "ok": False,
        "chunks_added": 0,
        "reason": (
            "HTML behavior failed for "
            "index.html: interaction"
        ),
    }

    learned = {
        "quality_reward": -0.65,
        "quality_signals": [
            "failed_status:-0.35",
            "artifact_validation_failed:-0.30",
        ],
        "failure_category":
            "ARTIFACT_VALIDATION_FAILED",
    }

    with (
        patch(
            "sophyane.code_memory."
            "sli_rich_site_compose."
            "compose_rich_topic_site",
            side_effect=compose,
        ),
        patch(
            "sophyane.code_memory."
            "promote_success."
            "promote_workspace",
            return_value=promotion,
        ),
        patch(
            "sophyane.sli_schema."
            "ensure_current_schema",
        ),
        patch(
            "sophyane.sli_learner."
            "learn_execution",
            return_value=learned,
        ) as learner,
    ):
        state = run_sli_graph(
            "make website on demis hassabis",
            workspace=tmp_path,
            max_retries=1,
        )

    assert state.success is True
    assert state.promoted is False

    assert state.meta[
        "promotion_reason"
    ].startswith(
        "HTML behavior failed"
    )

    assert any(
        error.startswith(
            "promotion-blocked:"
        )
        for error in state.errors
    )

    kwargs = learner.call_args.kwargs

    assert kwargs["status"] == "failed"

    assert (
        "HTML behavior failed"
        in kwargs["error"]
    )


def test_product_app_graph_records_validated_execution_learning(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.sli_graph as graph
    import sophyane.sli_learner as learner
    import sophyane.sli_schema as schema

    captured = {}

    def fake_classify(
        state,
        progress,
    ):
        del progress
        state.route = "product_app"
        return state

    def fake_product_reuse(
        state,
        progress,
    ):
        del progress
        return state

    def fake_product_app(
        state,
        progress,
    ):
        del progress

        target = (
            tmp_path
            / "index.html"
        )

        target.write_text(
            "<!doctype html><html><body>"
            "validated product app"
            "</body></html>",
            encoding="utf-8",
        )

        state.success = True
        state.report = (
            "Sophyane product-app synthesis\n"
            "Deterministic behavior validation: passed\n"
            "Success: True"
        )

        return state

    def fake_validate_and_promote(
        state,
        progress,
    ):
        del progress
        state.promoted = True
        state.chunks_added = 1
        return state

    def fake_ensure_current_schema():
        return None

    def fake_learn_execution(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "memory_id": 999,
            "quality_reward": 0.45,
            "atomic_learning": {
                "state":
                    "created",
            },
        }

    monkeypatch.setattr(
        graph,
        "classify",
        fake_classify,
    )

    monkeypatch.setattr(
        graph,
        "try_product_reuse",
        fake_product_reuse,
    )

    monkeypatch.setattr(
        graph,
        "try_product_app",
        fake_product_app,
    )

    monkeypatch.setattr(
        graph,
        "validate_and_promote",
        fake_validate_and_promote,
    )

    monkeypatch.setattr(
        schema,
        "ensure_current_schema",
        fake_ensure_current_schema,
    )

    monkeypatch.setattr(
        learner,
        "learn_execution",
        fake_learn_execution,
    )

    state = graph.run_sli_graph(
        "make nifdu email service",
        workspace=tmp_path,
        max_retries=1,
    )

    assert state.route == "product_app"
    assert state.success is True
    assert state.promoted is True

    assert (
        state.meta[
            "learning"
        ][
            "memory_id"
        ]
        == 999
    )

    assert captured[
        "request"
    ] == "make nifdu email service"

    assert captured[
        "status"
    ] == "succeeded"

    assert captured[
        "workspace_before"
    ] != captured[
        "workspace_after"
    ]

    assert str(
        captured[
            "trace_id"
        ]
    ).startswith(
        "product-app-"
    )


def test_product_app_success_learns_success_without_chunk_promotion(
    tmp_path,
    monkeypatch,
) -> None:
    import sophyane.sli_graph as graph
    import sophyane.sli_learner as learner
    import sophyane.sli_schema as schema

    captured = {}

    def fake_classify(
        state,
        progress,
    ):
        del progress
        state.route = "product_app"
        return state

    def fake_product_reuse(
        state,
        progress,
    ):
        del progress
        return state

    def fake_product_app(
        state,
        progress,
    ):
        del progress

        (
            tmp_path
            / "index.html"
        ).write_text(
            "<!doctype html>"
            "<html><body>"
            "validated product application"
            "</body></html>",
            encoding="utf-8",
        )

        state.success = True
        state.report = (
            "Sophyane product-app synthesis\n"
            "Deterministic behavior validation: passed\n"
            "Success: True"
        )

        return state

    def fake_validate_and_promote(
        state,
        progress,
    ):
        del progress

        # Product execution is valid, but no reusable
        # chunks were promoted. This must not convert
        # execution learning into a failure.
        state.promoted = False
        state.chunks_added = 0

        return state

    def fake_ensure_current_schema():
        return None

    def fake_learn_execution(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "memory_id": 999,
            "quality_reward": 0.45,
            "atomic_learning": {
                "state": "created",
            },
        }

    monkeypatch.setattr(
        graph,
        "classify",
        fake_classify,
    )

    monkeypatch.setattr(
        graph,
        "try_product_reuse",
        fake_product_reuse,
    )

    monkeypatch.setattr(
        graph,
        "try_product_app",
        fake_product_app,
    )

    monkeypatch.setattr(
        graph,
        "validate_and_promote",
        fake_validate_and_promote,
    )

    monkeypatch.setattr(
        schema,
        "ensure_current_schema",
        fake_ensure_current_schema,
    )

    monkeypatch.setattr(
        learner,
        "learn_execution",
        fake_learn_execution,
    )

    state = graph.run_sli_graph(
        "make validated local product application",
        workspace=tmp_path,
        max_retries=1,
    )

    assert state.route == "product_app"
    assert state.success is True
    assert state.promoted is False
    assert state.chunks_added == 0

    assert captured[
        "status"
    ] == "succeeded"

    assert captured[
        "reward"
    ] == 1.0

    assert str(
        captured[
            "trace_id"
        ]
    ).startswith(
        "product-app-"
    )

    assert (
        state.meta[
            "learning"
        ][
            "memory_id"
        ]
        == 999
    )
