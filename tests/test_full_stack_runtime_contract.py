from pathlib import Path

import sophyane.runtime_sli_capability_planner as planner


def test_full_stack_contract_reaches_adaptive_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured = {}

    def fake_original(
        *,
        initial_text,
        original_request,
        ask,
        workspace,
        max_steps,
        progress,
        operation=None,
    ):
        captured["initial_text"] = initial_text
        captured["operation"] = operation
        captured["original_request"] = original_request
        captured["workspace"] = workspace
        captured["max_steps"] = max_steps
        return "ok"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_original,
    )

    # Reinstall around our fake.
    monkeypatch.delattr(
        "sophyane.adaptive_execution._sli_capability_planner_installed",
        raising=False,
    )

    planner.install_sli_capability_planner()

    from sophyane import adaptive_execution

    result = adaptive_execution.run_adaptive_loop(
        initial_text="provider-plan",
        original_request=(
            "Build a SaaS with responsive web frontend, "
            "REST API, persistent SQLite database and automated tests."
        ),
        ask=lambda _message: "",
        workspace=tmp_path,
        max_steps=12,
        progress=lambda _message: None,
    )

    assert result == "ok"
    assert captured["operation"] is None

    initial = captured["initial_text"]
    request = captured["original_request"].lower()

    # Provider output is an executable protocol channel.
    # It must remain untouched.
    assert initial == "provider-plan"
    assert "full-stack architecture contract" not in initial.lower()

    # Architecture policy belongs in provider instruction context.
    assert "full-stack architecture contract" in request
    assert "python 3 standard library" in request
    assert "sqlite3" in request
    assert "threadinghttpserver" in request
    assert "vanilla javascript" in request
    assert "do not use java" in request
    assert "do not satisfy the request with only index.html" in request

    assert captured["max_steps"] >= 32


def test_full_stack_classifier_still_selected() -> None:
    plan = planner.classify(
        """
        Build a complete project-management SaaS with
        responsive web frontend, REST API,
        persistent database and automated tests.
        """
    )

    assert (
        plan.builder
        == "FULL_STACK_PROVIDER_BOUNDED"
    )

    assert (
        plan.project_type
        == "full_stack_web_application"
    )


def test_capability_planner_forwards_operation_to_full_stack_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured = {}

    def fake_original(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_original,
    )
    monkeypatch.delattr(
        "sophyane.adaptive_execution._sli_capability_planner_installed",
        raising=False,
    )

    planner.install_sli_capability_planner()

    from sophyane import adaptive_execution

    operation = object()

    result = adaptive_execution.run_adaptive_loop(
        initial_text='{"type":"write_file","path":"backend/app.py","content":"x"}',
        original_request=(
            "Build a production web application with a responsive frontend, "
            "Python backend, REST API, persistent SQLite database and "
            "automated tests."
        ),
        ask=lambda _message: "",
        workspace=tmp_path,
        max_steps=12,
        operation=operation,
    )

    assert result == "ok"
    assert captured["operation"] is operation


def test_capability_planner_forwards_operation_to_ordinary_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured = {}

    def fake_original(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_original,
    )
    monkeypatch.delattr(
        "sophyane.adaptive_execution._sli_capability_planner_installed",
        raising=False,
    )

    planner.install_sli_capability_planner()

    from sophyane import adaptive_execution

    operation = object()

    result = adaptive_execution.run_adaptive_loop(
        initial_text='{"type":"write_file","path":"note.txt","content":"x"}',
        original_request="Create note.txt containing x.",
        ask=lambda _message: "",
        workspace=tmp_path,
        max_steps=12,
        operation=operation,
    )

    assert result == "ok"
    assert captured["operation"] is operation
