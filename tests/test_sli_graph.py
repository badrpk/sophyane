

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
