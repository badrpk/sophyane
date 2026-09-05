from sophyane.adaptive_execution import (
    _browser_request,
)

from sophyane.runtime_software_routing_guard import (
    _is_software_project,
)


REQUEST_A = (
    "Implement the first practical milestone from this design "
    "using Sophyane's existing architecture. First inspect the "
    "repository and identify what already exists, what is missing, "
    "and the smallest safe implementation path. Do not duplicate "
    "existing capabilities."
)

REQUEST_B = (
    "Build me a dashboard website for these capabilities."
)

REQUEST_C = (
    "show me the implementation flow"
)

REQUEST_D = (
    "Implement this architecture in the existing repository"
)


def test_repository_milestone_request_is_not_browser_artifact():
    assert _is_software_project(
        REQUEST_A
    ) is True

    assert _browser_request(
        REQUEST_A
    ) is False


def test_explicit_dashboard_website_remains_browser_artifact():
    assert _browser_request(
        REQUEST_B
    ) is True


def test_flow_description_is_not_software_or_browser_execution():
    assert _is_software_project(
        REQUEST_C
    ) is False

    assert _browser_request(
        REQUEST_C
    ) is False


def test_existing_repository_implementation_is_software():
    assert _is_software_project(
        REQUEST_D
    ) is True

    assert _browser_request(
        REQUEST_D
    ) is False


def test_generic_design_word_alone_is_not_browser_authority():
    assert (
        _browser_request(
            "Implement this design in the existing repository"
        )
        is False
    )


def test_explicit_browser_design_remains_browser_authority():
    assert (
        _browser_request(
            "Design and build a website dashboard"
        )
        is True
    )


def test_read_only_browser_diagnosis_is_not_browser_artifact():
    request = (
        "Audit Sophyane. Do not create files. Inspect the current browser "
        "routing defect and report the exact source location."
    )

    assert _browser_request(request) is False


def test_prior_index_html_failure_diagnosis_is_not_browser_artifact():
    request = (
        "The previous run incorrectly created index.html. Diagnose why "
        "a controller request was routed into browser product generation. "
        "Do not modify anything."
    )

    assert _browser_request(request) is False


def test_no_edit_authority_rejects_direct_and_batched_writes():
    from sophyane import adaptive_execution as adaptive

    direct = {
        "type": "write_file",
        "path": "bad.txt",
        "content": "mutation",
    }
    batch = {
        "type": "batch",
        "actions": [
            {
                "type": "run_command",
                "command": "git status --short",
            },
            {
                "type": "append_file",
                "path": "bad.txt",
                "content": "mutation",
            },
        ],
    }

    assert adaptive._no_edit_action_problem(direct)
    assert adaptive._no_edit_action_problem(batch)


def test_no_edit_authority_allows_inspection_and_verification_commands():
    from sophyane import adaptive_execution as adaptive

    commands = (
        "git status --short",
        "git diff -- src/sophyane/adaptive_execution.py",
        "grep -RIn browser src/sophyane",
        "sed -n '1,120p' src/sophyane/adaptive_execution.py",
        "cat src/sophyane/adaptive_execution.py",
        "pytest -q",
        ".venv/bin/python -m pytest tests -q",
    )

    for command in commands:
        action = {
            "type": "run_command",
            "command": command,
        }
        assert adaptive._no_edit_action_problem(action) == ""


def test_no_edit_authority_rejects_mutating_commands():
    from sophyane import adaptive_execution as adaptive

    commands = (
        "echo MUTATION > bad.txt",
        "touch bad.txt",
        "rm bad.txt",
        '''python -c "open('bad.txt','w').write('x')"''',
    )

    for command in commands:
        action = {
            "type": "run_command",
            "command": command,
        }
        assert adaptive._no_edit_action_problem(action)


def test_explicit_no_create_request_blocks_provider_write_before_execution(
    tmp_path,
    monkeypatch,
):
    from sophyane import adaptive_execution as adaptive

    executed = []

    def forbidden_execute(*args, **kwargs):
        executed.append((args, kwargs))
        raise AssertionError(
            "provider mutation reached execution boundary"
        )

    monkeypatch.setattr(
        adaptive,
        "_execute",
        forbidden_execute,
    )

    result = adaptive.run_adaptive_loop(
        initial_text=(
            '{"action":{"type":"write_file",'
            '"path":"should-not-exist.txt",'
            '"content":"MUTATION"}}'
        ),
        original_request=(
            "Audit Sophyane. Do not create files. "
            "Inspect the browser routing defect and report only."
        ),
        ask=lambda prompt: (_ for _ in ()).throw(
            AssertionError("provider repair must not be requested")
        ),
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert not executed
    assert not (tmp_path / "should-not-exist.txt").exists()
    assert "stopped safely" in result.lower()


def test_adaptive_loop_honors_explicit_max_steps(
    tmp_path,
    monkeypatch,
):
    from sophyane import adaptive_execution as adaptive

    executions = []

    def failing_execute(
        runtime,
        action,
        workspace,
        progress,
    ):
        executions.append(dict(action))
        return False, "synthetic execution failure"

    monkeypatch.setattr(
        adaptive,
        "_execute",
        failing_execute,
    )

    provider_action = (
        '{"action":{"type":"write_file",'
        '"path":"bounded.txt",'
        '"content":"x"}}'
    )

    result = adaptive.run_adaptive_loop(
        initial_text=provider_action,
        original_request="Create bounded.txt.",
        ask=lambda prompt: provider_action,
        workspace=tmp_path,
        max_steps=1,
        progress=lambda message: None,
    )

    assert len(executions) == 1
    assert "bounded execution loop" in result.lower()
